"""Backups of the SQLite database: nightly copies, pre-upgrade copies, export and import.

Every copy is made with SQLite's backup API, so it is consistent even while the printer
worker is writing. Copies go to `backups/` next to the database, which is inside the data
folder on the SSD, so they survive a rebuild of the container.

Restore from the command line, with the API stopped or not:

    python -m app.backup restore /data/backups/nightly-20261024-030000.db

That replaces the live database after checking the file, keeps the old one as a safety copy,
and runs any needed schema upgrade.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import sys
import tempfile
import threading
from collections.abc import Callable
from contextlib import closing
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app import migrations

logger = logging.getLogger("printarr.backup")

SQLITE_HEADER = b"SQLite format 3\x00"
NIGHTLY_PREFIX = "nightly-"
PRE_UPGRADE_PREFIX = "pre-upgrade-"
PRE_IMPORT_PREFIX = "pre-import-"
KEEP_PRE_UPGRADE = 5


class BackupError(ValueError):
    """The file is not a usable printarr database."""


def _stamp(now: datetime) -> str:
    return now.strftime("%Y%m%d-%H%M%S")


def snapshot(source: sqlite3.Connection, dest: Path) -> Path:
    """Copy the open database to `dest`. The file appears only once it is complete."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.unlink(missing_ok=True)
    with closing(sqlite3.connect(tmp)) as target:
        source.backup(target)
    os.replace(tmp, dest)
    return dest


def snapshot_path(directory: Path, label: str, now: datetime) -> Path:
    return directory / f"{label}-{_stamp(now)}.db"


def verify(path: Path) -> int:
    """Check a database file. Returns its schema version, or raises BackupError."""
    try:
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as conn:
            check = conn.execute("PRAGMA integrity_check").fetchone()[0]
            if check != "ok":
                raise BackupError(f"integrity check failed: {check}")
            if not migrations.has_tables(conn):
                raise BackupError("no tickets table: this is not a printarr database")
            version = migrations.schema_version(conn)
    except sqlite3.DatabaseError as exc:
        raise BackupError(f"not a readable SQLite database: {exc}") from None
    if version > migrations.LATEST_VERSION:
        raise BackupError(
            f"backup schema is version {version}; this printarr supports up to "
            f"{migrations.LATEST_VERSION}"
        )
    return version


def prune(directory: Path, prefix: str, keep: int) -> list[Path]:
    """Delete the oldest files whose name starts with `prefix`, keeping the newest `keep`."""
    if not directory.is_dir():
        return []
    files = sorted(p for p in directory.glob(f"{prefix}*.db") if p.is_file())
    doomed = files[: max(0, len(files) - keep)]
    for path in doomed:
        path.unlink(missing_ok=True)
    return doomed


def pre_upgrade_copy(backup_dir: Path) -> Callable[[sqlite3.Connection, int], None]:
    """Hook for migrations.migrate: copy the database before a schema upgrade."""

    def copy(conn: sqlite3.Connection, version: int) -> None:
        stamp = _stamp(datetime.now())
        dest = snapshot(conn, backup_dir / f"{PRE_UPGRADE_PREFIX}v{version}-{stamp}.db")
        logger.info("copied database to %s before upgrading from schema %d", dest, version)
        prune(backup_dir, PRE_UPGRADE_PREFIX, KEEP_PRE_UPGRADE)

    return copy


def export_bytes(conn: sqlite3.Connection, backup_dir: Path) -> bytes:
    """A consistent copy of the database as bytes, for download."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=backup_dir, suffix=".export")
    os.close(fd)
    temp = Path(name)
    try:
        with closing(sqlite3.connect(temp)) as target:
            conn.backup(target)
        return temp.read_bytes()
    finally:
        temp.unlink(missing_ok=True)


def import_bytes(data: bytes, live_path: str, backup_dir: Path, now: datetime) -> dict:
    """Replace the live database with `data` after checking it.

    The live database is first copied to backups/ as a safety copy. Returns a summary.
    """
    if not data.startswith(SQLITE_HEADER):
        raise BackupError("the file is not an SQLite database")
    backup_dir.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=backup_dir, suffix=".import")
    os.close(fd)
    incoming = Path(name)
    try:
        incoming.write_bytes(data)
        version = verify(incoming)
        Path(live_path).parent.mkdir(parents=True, exist_ok=True)
        safety = None
        if Path(live_path).exists():
            with closing(sqlite3.connect(live_path, timeout=10)) as live:
                safety = snapshot(live, snapshot_path(backup_dir, PRE_IMPORT_PREFIX.rstrip("-"), now))
        with closing(sqlite3.connect(incoming)) as source, closing(
            sqlite3.connect(live_path, timeout=30)
        ) as live:
            source.backup(live)
            live.execute("PRAGMA journal_mode=WAL")
            migrations.migrate(live, before_upgrade=pre_upgrade_copy(backup_dir))
            final = migrations.schema_version(live)
    finally:
        incoming.unlink(missing_ok=True)
    return {
        "status": "restored",
        "schema_version_in_file": version,
        "schema_version": final,
        "safety_copy": str(safety) if safety else None,
    }


class NightlyBackup:
    """Writes one copy each day at the given local hour and keeps the newest `keep`."""

    def __init__(self, live_path: str, backup_dir: Path, zone: ZoneInfo, hour: int, keep: int) -> None:
        self.live_path = live_path
        self.backup_dir = backup_dir
        self.zone = zone
        self.hour = hour
        self.keep = keep
        self.last_day: str | None = None

    def due(self, now: datetime) -> bool:
        return now.hour == self.hour and now.date().isoformat() != self.last_day

    def run_once(self, now: datetime | None = None) -> Path | None:
        """Make the copy if one is due. Returns the new file, or None."""
        now = now or datetime.now(self.zone)
        if not self.due(now):
            return None
        if not Path(self.live_path).exists():
            return None
        with closing(sqlite3.connect(self.live_path, timeout=10)) as live:
            dest = snapshot(live, snapshot_path(self.backup_dir, NIGHTLY_PREFIX.rstrip("-"), now))
        self.last_day = now.date().isoformat()
        prune(self.backup_dir, NIGHTLY_PREFIX, self.keep)
        logger.info("nightly backup written to %s", dest)
        return dest


class NightlyThread(threading.Thread):
    def __init__(self, nightly: NightlyBackup, interval: float = 60.0) -> None:
        super().__init__(name="printarr-backup", daemon=True)
        self.nightly = nightly
        self.interval = interval
        self._stop_event = threading.Event()

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.nightly.run_once()
            except Exception:
                logger.exception("nightly backup failed")
            self._stop_event.wait(self.interval)

    def stop(self) -> None:
        self._stop_event.set()
        self.join(timeout=5)


def _restore_cli(argv: list[str]) -> int:
    from app.config import load_settings

    if len(argv) != 2 or argv[0] != "restore":
        print("usage: python -m app.backup restore <backup-file>", file=sys.stderr)
        return 2
    settings = load_settings()
    source = Path(argv[1])
    try:
        result = import_bytes(source.read_bytes(), settings.db_path, Path(settings.db_path).parent / "backups",
                              datetime.now(settings.tzinfo))
    except (BackupError, OSError) as exc:
        print(f"restore failed: {exc}", file=sys.stderr)
        return 1
    print(f"restored {source} (schema {result['schema_version']})")
    if result["safety_copy"]:
        print(f"previous database kept at {result['safety_copy']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_restore_cli(sys.argv[1:]))
