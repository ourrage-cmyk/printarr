"""SQLite persistence for tickets. Times are stored as UTC epoch milliseconds.

Ticket lifecycle:

    pending --claimed--> printing --ok--> sent
       ^                    |
       |                    +--error, attempts left--> pending (next_attempt_ms moved back)
       |                    +--error, no attempts left--> failed
       +--retry-- failed / cancelled
    pending --cancel--> cancelled
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from collections.abc import Callable
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app import backup, migrations

MAX_ERROR_LENGTH = 500

LOG_COLUMNS = ("kind", "tone", "template_id", "status", "choice_source")


def _log_filters(
    recipient: str | None,
    kind: str | None,
    tone: str | None,
    template_id: int | None,
    status: str | None,
    since_ms: int | None,
) -> tuple[list[str], list[Any]]:
    wanted = {
        "recipient = ?": recipient,
        "kind = ?": kind,
        "tone = ?": tone,
        "template_id = ?": template_id,
        "status = ?": status,
        "created_at_ms >= ?": since_ms,
    }
    clauses = [clause for clause, value in wanted.items() if value is not None]
    params = [value for value in wanted.values() if value is not None]
    return clauses, params


class TicketNotFound(LookupError):
    pass


class TicketStateError(ValueError):
    pass


def now_ms() -> int:
    return time.time_ns() // 1_000_000


def _iso(ms: int | None) -> str | None:
    return None if ms is None else datetime.fromtimestamp(ms / 1000, tz=UTC).isoformat()


def _to_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["decorations"] = [d for d in data["decorations"].split(",") if d]
    data["send_at"] = _iso(data["send_at_ms"])
    data["next_attempt_at"] = _iso(data["next_attempt_ms"])
    data["created_at"] = _iso(data["created_at_ms"])
    data["updated_at"] = _iso(data["updated_at_ms"])
    data["printed_at"] = _iso(data["printed_at_ms"])
    return data


class TicketStore:
    def __init__(self, path: str, backup_dir: Path | None = None) -> None:
        self.path = path
        # Copies taken before a schema upgrade go here. Default: a backups/ folder beside the database.
        self.backup_dir = backup_dir or Path(path).parent / "backups"

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    def init(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            migrations.migrate(conn, before_upgrade=backup.pre_upgrade_copy(self.backup_dir))

    def create(
        self,
        *,
        recipient: str,
        message: str,
        send_at_ms: int,
        template_id: int,
        decorations: tuple[str, ...],
        selection: str,
        sender: str | None = None,
        title: str | None = None,
        held: bool = False,
        hold_key: str | None = None,
        text_state: str = "formatted",
        blocks_json: str = "[]",
        kind: str = "note",
        tone: str = "neutral",
        from_user: str | None = None,
        to_user: str | None = None,
        render_ms: int | None = None,
        choice_source: str | None = None,
        model_scores: str = "",
        idempotency_key: str | None = None,
        slots_json: str = "",
    ) -> dict[str, Any]:
        """Queue a ticket. A held ticket waits until released, then prints at once.

        A ticket from one recipient's user to the other is an inbox item: it is 'unread' until
        it is printed in the evening rundown or seen.
        """
        if idempotency_key:
            existing = self.get_by_key(idempotency_key)
            if existing is not None:
                return existing
        ticket_id = uuid.uuid4().hex
        now = now_ms()
        status = "held" if held else "pending"
        inbox_state = "unread" if from_user and to_user else None
        with closing(self._connect()) as conn:
            try:
                conn.execute(
                """
                INSERT INTO tickets (id, recipient, sender, title, message, status, hold_key,
                                     send_at_ms, next_attempt_ms, template_id, text_state,
                                     blocks_json, decorations, selection, created_at_ms, updated_at_ms,
                                     kind, tone, from_user, to_user, inbox_state, render_ms,
                                     choice_source, model_scores, idempotency_key, slots_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ticket_id, recipient, sender, title, message, status, hold_key,
                    send_at_ms, send_at_ms, template_id, text_state, blocks_json, ",".join(decorations),
                    selection, now, now, kind, tone, from_user, to_user, inbox_state, render_ms,
                    choice_source or selection, model_scores, idempotency_key, slots_json,
                ),
            )
            except sqlite3.IntegrityError:
                # A concurrent request with the same key won the race: return its ticket.
                existing = self.get_by_key(idempotency_key) if idempotency_key else None
                if existing is None:
                    raise
                return existing
        result = self.get(ticket_id)
        assert result is not None
        return result

    def get_by_key(self, idempotency_key: str) -> dict[str, Any] | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM tickets WHERE idempotency_key = ?", (idempotency_key,)
            ).fetchone()
        return _to_dict(row) if row else None

    def export_bytes(self) -> bytes:
        """A consistent copy of the whole database, for download."""
        with closing(self._connect()) as conn:
            return backup.export_bytes(conn, self.backup_dir)

    def get(self, ticket_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        return _to_dict(row) if row else None

    def search(
        self,
        *,
        status: str | None = None,
        recipient: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if recipient:
            clauses.append("recipient = ?")
            params.append(recipient)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = (
            f"SELECT * FROM tickets {where} "
            "ORDER BY created_at_ms DESC LIMIT ? OFFSET ?"
        )
        params += [limit, offset]
        with closing(self._connect()) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_to_dict(row) for row in rows]

    def log(
        self,
        *,
        recipient: str | None = None,
        kind: str | None = None,
        tone: str | None = None,
        template_id: int | None = None,
        status: str | None = None,
        since_ms: int | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Every ticket that matches, oldest first, for the timeline and exports."""
        clauses, params = _log_filters(recipient, kind, tone, template_id, status, since_ms)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT * FROM tickets {where} ORDER BY created_at_ms ASC LIMIT ? OFFSET ?"
        with closing(self._connect()) as conn:
            rows = conn.execute(sql, [*params, limit, offset]).fetchall()
        return [_to_dict(row) for row in rows]

    def log_counts(
        self,
        column: str,
        *,
        recipient: str | None = None,
        since_ms: int | None = None,
    ) -> dict[str, int]:
        """Ticket counts grouped by one logged column: kind, tone, template_id, status or choice_source."""
        if column not in LOG_COLUMNS:
            raise ValueError(f"cannot group the log by {column}")
        clauses, params = _log_filters(recipient, None, None, None, None, since_ms)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT {column} AS key, COUNT(*) AS n FROM tickets {where} GROUP BY {column} ORDER BY n DESC"
        with closing(self._connect()) as conn:
            rows = conn.execute(sql, params).fetchall()
        return {str(row["key"]): row["n"] for row in rows}

    def cancel(self, ticket_id: str) -> dict[str, Any]:
        return self._guarded_update(
            ticket_id, ("pending",), "status = 'cancelled'", ()
        )

    def release(self, ticket_id: str) -> dict[str, Any]:
        """Release a held ticket so it prints now. Its receipt time becomes the release time."""
        now = now_ms()
        return self._guarded_update(
            ticket_id,
            ("held",),
            "status = 'pending', send_at_ms = ?, next_attempt_ms = ?",
            (now, now),
        )

    def release_hold(self, hold_key: str) -> list[dict[str, Any]]:
        """Release every held ticket with this key, for example "user-home"."""
        now = now_ms()
        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                ids = [
                    row["id"]
                    for row in conn.execute(
                        "SELECT id FROM tickets WHERE status = 'held' AND hold_key = ?",
                        (hold_key,),
                    ).fetchall()
                ]
                for ticket_id in ids:
                    conn.execute(
                        """
                        UPDATE tickets
                        SET status = 'pending', send_at_ms = ?, next_attempt_ms = ?, updated_at_ms = ?
                        WHERE id = ?
                        """,
                        (now, now, now, ticket_id),
                    )
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        released = [self.get(ticket_id) for ticket_id in ids]
        return [ticket for ticket in released if ticket is not None]

    def get_setting(self, key: str) -> str | None:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_setting(self, key: str, value: str) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def requeue(self, ticket_id: str) -> dict[str, Any]:
        return self._guarded_update(
            ticket_id,
            ("failed", "cancelled"),
            "status = 'pending', attempts = 0, last_error = NULL, next_attempt_ms = ?",
            (now_ms(),),
        )

    def claim_due(self, at_ms: int, limit: int) -> list[dict[str, Any]]:
        """Atomically move due pending tickets to 'printing' and count the attempt."""
        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                ids = [
                    row["id"]
                    for row in conn.execute(
                        """
                        SELECT id FROM tickets
                        WHERE status = 'pending' AND next_attempt_ms <= ?
                        ORDER BY next_attempt_ms
                        LIMIT ?
                        """,
                        (at_ms, limit),
                    ).fetchall()
                ]
                for ticket_id in ids:
                    conn.execute(
                        """
                        UPDATE tickets
                        SET status = 'printing', attempts = attempts + 1, updated_at_ms = ?
                        WHERE id = ?
                        """,
                        (at_ms, ticket_id),
                    )
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        claimed = [self.get(ticket_id) for ticket_id in ids]
        return [ticket for ticket in claimed if ticket is not None]

    def mark_sent(self, ticket_id: str, print_ms: int | None = None) -> None:
        now = now_ms()
        with closing(self._connect()) as conn:
            conn.execute(
                """
                UPDATE tickets
                SET status = 'sent', printed_at_ms = ?, updated_at_ms = ?, last_error = NULL,
                    print_ms = ?
                WHERE id = ?
                """,
                (now, now, print_ms, ticket_id),
            )

    def record_failure(self, ticket_id: str, error: str, retry_at_ms: int | None) -> None:
        """Retry later when retry_at_ms is set; otherwise mark the ticket failed."""
        now = now_ms()
        status = "pending" if retry_at_ms is not None else "failed"
        with closing(self._connect()) as conn:
            conn.execute(
                """
                UPDATE tickets
                SET status = ?, next_attempt_ms = COALESCE(?, next_attempt_ms),
                    last_error = ?, updated_at_ms = ?
                WHERE id = ?
                """,
                (status, retry_at_ms, error[:MAX_ERROR_LENGTH], now, ticket_id),
            )

    def count_due(self, at_ms: int) -> int:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM tickets WHERE status = 'pending' AND next_attempt_ms <= ?",
                (at_ms,),
            ).fetchone()
        return int(row["n"])

    def fail_interrupted(self, at_ms: int | None = None) -> list[str]:
        """Mark tickets left in 'printing' by a crash or restart as failed. Returns their ids.

        They are not re-queued automatically. The crash may have happened after the bytes
        reached the printer, so printing again could give a duplicate. Use requeue() to
        print one again on purpose.
        """
        now = now_ms() if at_ms is None else at_ms
        error = "interrupted by a restart while printing; not reprinted automatically"
        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                ids = [
                    row["id"]
                    for row in conn.execute("SELECT id FROM tickets WHERE status = 'printing'").fetchall()
                ]
                for ticket_id in ids:
                    conn.execute(
                        """
                        UPDATE tickets
                        SET status = 'failed', last_error = ?, next_attempt_ms = ?, updated_at_ms = ?
                        WHERE id = ?
                        """,
                        (error, now, now, ticket_id),
                    )
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        return ids

    def _guarded_update(
        self,
        ticket_id: str,
        allowed_from: tuple[str, ...],
        assignments: str,
        params: tuple[Any, ...],
    ) -> dict[str, Any]:
        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT status FROM tickets WHERE id = ?", (ticket_id,)
                ).fetchone()
                if row is None:
                    raise TicketNotFound(ticket_id)
                if row["status"] not in allowed_from:
                    raise TicketStateError(
                        f"ticket is {row['status']}; expected {' or '.join(allowed_from)}"
                    )
                conn.execute(
                    f"UPDATE tickets SET {assignments}, updated_at_ms = ? WHERE id = ?",
                    (*params, now_ms(), ticket_id),
                )
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        result = self.get(ticket_id)
        assert result is not None
        return result


Clock = Callable[[], int]
