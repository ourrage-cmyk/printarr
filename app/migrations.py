"""Versioned SQLite schema. Runs on every start and never drops data.

The schema version lives in SQLite's own `user_version` header field, so no extra table is needed.

Rules for changing the schema:

- Append a new step to MIGRATIONS. Never edit or reorder an existing step, because a database
  that is already past it will not run it again.
- A step must keep existing rows. Prefer ADD COLUMN, CREATE INDEX and CREATE TABLE. To change a
  CHECK constraint or drop a column, build a new table, copy the rows across, then rename it.
- Each step runs in its own transaction together with its version bump, so a failed step leaves
  the database as it was.
- A database newer than this code is refused. That protects a rollback to an older image: restore
  a backup taken by the older version instead of running it on a newer schema.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

BEFORE_UPGRADE = Callable[[sqlite3.Connection, int], None]


class SchemaTooNew(RuntimeError):
    """The database was written by a newer version of printarr than this one."""


def _create_base(conn: sqlite3.Connection) -> None:
    """Version 1: the first release's tables. IF NOT EXISTS makes it a no-op on existing data."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tickets (
            id              TEXT PRIMARY KEY,
            recipient       TEXT NOT NULL,
            sender          TEXT,
            title           TEXT,
            message         TEXT NOT NULL,
            status          TEXT NOT NULL
                            CHECK (status IN ('held', 'pending', 'printing', 'sent', 'failed', 'cancelled')),
            hold_key        TEXT,
            send_at_ms      INTEGER NOT NULL,
            next_attempt_ms INTEGER NOT NULL,
            attempts        INTEGER NOT NULL DEFAULT 0,
            last_error      TEXT,
            template_id     INTEGER NOT NULL,
            text_state      TEXT NOT NULL DEFAULT 'formatted',
            blocks_json     TEXT NOT NULL DEFAULT '[]',
            decorations     TEXT NOT NULL DEFAULT '',
            selection       TEXT NOT NULL CHECK (selection IN ('explicit', 'model', 'rule')),
            created_at_ms   INTEGER NOT NULL,
            updated_at_ms   INTEGER NOT NULL,
            printed_at_ms   INTEGER
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS tickets_due ON tickets (status, next_attempt_ms)")
    conn.execute("CREATE INDEX IF NOT EXISTS tickets_recipient ON tickets (recipient, created_at_ms)")
    conn.execute("CREATE INDEX IF NOT EXISTS tickets_hold ON tickets (status, hold_key)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key    TEXT PRIMARY KEY,
            value  TEXT NOT NULL
        )
        """
    )


# Columns added after the first release. Version 2 adds any that are missing.
ADDED_COLUMNS: tuple[tuple[str, str], ...] = (
    ("kind", "TEXT NOT NULL DEFAULT 'note'"),
    ("tone", "TEXT NOT NULL DEFAULT 'neutral'"),
    ("from_user", "TEXT"),
    ("to_user", "TEXT"),
    ("inbox_state", "TEXT"),
    ("render_ms", "INTEGER"),
    ("print_ms", "INTEGER"),
    ("choice_source", "TEXT"),
    ("model_scores", "TEXT NOT NULL DEFAULT ''"),
    ("idempotency_key", "TEXT"),
)


def _add_logging_columns(conn: sqlite3.Connection) -> None:
    """Version 2: the log columns. Skips any column a pre-migration database already has."""
    have = {row["name"] for row in conn.execute("PRAGMA table_info(tickets)")}
    for name, definition in ADDED_COLUMNS:
        if name not in have:
            conn.execute(f"ALTER TABLE tickets ADD COLUMN {name} {definition}")


def _add_idempotency_index(conn: sqlite3.Connection) -> None:
    """Version 3: one ticket per idempotency key. Rows without a key are not constrained."""
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS tickets_idempotency "
        "ON tickets (idempotency_key) WHERE idempotency_key IS NOT NULL"
    )


def _add_slots_column(conn: sqlite3.Connection) -> None:
    """Version 4: the filled slots of a slot template, stored with the ticket for the log."""
    have = {row["name"] for row in conn.execute("PRAGMA table_info(tickets)")}
    if "slots_json" not in have:
        conn.execute("ALTER TABLE tickets ADD COLUMN slots_json TEXT NOT NULL DEFAULT ''")


def _add_delivery_columns(conn: sqlite3.Connection) -> None:
    """Version 5: how a ticket is delivered (now, at, on_release) and which strip printed it."""
    have = {row["name"] for row in conn.execute("PRAGMA table_info(tickets)")}
    for name, definition in (
        ("delivery", "TEXT NOT NULL DEFAULT 'now'"),
        ("strip_id", "TEXT"),
        ("strip_trigger", "TEXT"),
    ):
        if name not in have:
            conn.execute(f"ALTER TABLE tickets ADD COLUMN {name} {definition}")


MIGRATIONS: tuple[Callable[[sqlite3.Connection], None], ...] = (
    _create_base,  # version 1
    _add_logging_columns,  # version 2
    _add_idempotency_index,  # version 3
    _add_slots_column,  # version 4
    _add_delivery_columns,  # version 5
)

LATEST_VERSION = len(MIGRATIONS)


def schema_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def has_tables(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'tickets'"
    ).fetchone()
    return row is not None


def migrate(conn: sqlite3.Connection, before_upgrade: BEFORE_UPGRADE | None = None) -> int:
    """Bring the database up to LATEST_VERSION. Returns the version it was at before.

    `before_upgrade(conn, version)` runs first when there is something to upgrade and the
    database already holds tickets, so a copy can be taken before any change is made.
    """
    current = schema_version(conn)
    if current > LATEST_VERSION:
        raise SchemaTooNew(
            f"database schema is version {current}, but this printarr supports up to "
            f"{LATEST_VERSION}. Restore a backup from the older version instead."
        )
    if current == LATEST_VERSION:
        return current
    if before_upgrade is not None and has_tables(conn):
        before_upgrade(conn, current)
    for version in range(current + 1, LATEST_VERSION + 1):
        step = MIGRATIONS[version - 1]
        conn.execute("BEGIN IMMEDIATE")
        try:
            step(conn)
            conn.execute(f"PRAGMA user_version = {int(version)}")
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    return current
