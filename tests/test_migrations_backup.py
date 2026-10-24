import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app import backup, migrations
from app.main import create_app
from app.store import TicketStore

LONDON = ZoneInfo("Europe/London")


def make_ticket(store, message="hi"):
    return store.create(
        recipient="yannic", message=message, send_at_ms=0,
        template_id=1, decorations=(), selection="rule",
    )


def version_of(path):
    with sqlite3.connect(path) as conn:
        return conn.execute("PRAGMA user_version").fetchone()[0]


def first_release_database(path):
    """A database as the first release wrote it: tables, a ticket, no version, no log columns."""
    with sqlite3.connect(path) as conn:
        migrations._create_base(conn)
        conn.execute(
            "INSERT INTO tickets (id, recipient, message, status, send_at_ms, next_attempt_ms, "
            "template_id, selection, created_at_ms, updated_at_ms) "
            "VALUES ('old1', 'yannic', 'kept', 'sent', 0, 0, 1, 'rule', 0, 0)"
        )


def test_new_database_is_at_latest_version(tmp_path):
    path = tmp_path / "db" / "printarr.db"
    TicketStore(str(path)).init()
    assert version_of(path) == migrations.LATEST_VERSION


def test_first_release_database_upgrades_and_keeps_rows(tmp_path):
    path = tmp_path / "printarr.db"
    first_release_database(path)
    TicketStore(str(path)).init()
    store = TicketStore(str(path))
    assert version_of(path) == migrations.LATEST_VERSION
    assert store.get("old1")["message"] == "kept"
    assert store.get("old1")["kind"] == "note"


def test_upgrade_takes_a_copy_before_changing_anything(tmp_path):
    path = tmp_path / "printarr.db"
    first_release_database(path)
    TicketStore(str(path)).init()
    copies = list((tmp_path / "backups").glob("pre-upgrade-v0-*.db"))
    assert len(copies) == 1
    assert version_of(copies[0]) == 0
    with sqlite3.connect(copies[0]) as conn:
        names = {row[1] for row in conn.execute("PRAGMA table_info(tickets)")}
    assert "kind" not in names


def test_second_start_does_not_upgrade_or_copy_again(tmp_path):
    path = tmp_path / "printarr.db"
    TicketStore(str(path)).init()
    TicketStore(str(path)).init()
    assert not (tmp_path / "backups").exists()


def test_database_from_a_newer_version_is_refused(tmp_path):
    path = tmp_path / "printarr.db"
    TicketStore(str(path)).init()
    with sqlite3.connect(path) as conn:
        conn.execute(f"PRAGMA user_version = {migrations.LATEST_VERSION + 1}")
    with pytest.raises(migrations.SchemaTooNew):
        TicketStore(str(path)).init()


def test_failed_step_rolls_back_and_keeps_version(tmp_path, monkeypatch):
    path = tmp_path / "printarr.db"
    with closing(sqlite3.connect(path)) as conn:
        migrations._create_base(conn)
        conn.execute("PRAGMA user_version = 1")
        conn.commit()

    def broken(conn):
        conn.execute("ALTER TABLE tickets ADD COLUMN kind TEXT")
        conn.execute("THIS IS NOT SQL")

    monkeypatch.setattr(migrations, "MIGRATIONS", (migrations._create_base, broken))
    with pytest.raises(sqlite3.OperationalError):
        TicketStore(str(path)).init()
    assert version_of(path) == 1
    with sqlite3.connect(path) as conn:
        names = {row[1] for row in conn.execute("PRAGMA table_info(tickets)")}
    assert "kind" not in names


def test_export_is_a_usable_database_and_import_restores_it(settings, tmp_path):
    app = create_app(settings)
    with TestClient(app) as client:
        client.post("/api/v1/tickets", json={"recipient": "yannic", "message": "keep me"})
        exported = client.get("/api/v1/backup/export")
        assert exported.status_code == 200
        assert "attachment" in exported.headers["content-disposition"]
        client.post("/api/v1/tickets", json={"recipient": "yannic", "message": "lost later"})

        refused = client.post("/api/v1/backup/import", content=exported.content)
        assert refused.status_code == 400

        restored = client.post("/api/v1/backup/import?confirm=replace", content=exported.content)
        assert restored.status_code == 200, restored.text
        assert restored.json()["safety_copy"]
        listed = client.get("/api/v1/tickets").json()
        assert [t["message"] for t in listed] == ["keep me"]


def test_import_rejects_files_that_are_not_printarr_databases(settings):
    with TestClient(create_app(settings)) as client:
        assert client.post("/api/v1/backup/import?confirm=replace", content=b"hello").status_code == 422
        empty = Path(settings.db_path).parent / "other.db"
        empty.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(empty) as conn:
            conn.execute("CREATE TABLE other (x)")
        response = client.post(
            "/api/v1/backup/import?confirm=replace", content=empty.read_bytes()
        )
        assert response.status_code == 422
        assert "not a printarr database" in response.text


def test_import_refuses_a_backup_from_a_newer_version(settings):
    with TestClient(create_app(settings)) as client:
        exported = client.get("/api/v1/backup/export").content
    newer = Path(settings.db_path).parent / "newer.db"
    newer.write_bytes(exported)
    with closing(sqlite3.connect(newer)) as conn:
        conn.execute(f"PRAGMA user_version = {migrations.LATEST_VERSION + 1}")
        conn.commit()
    with TestClient(create_app(settings)) as client:
        response = client.post("/api/v1/backup/import?confirm=replace", content=newer.read_bytes())
    assert response.status_code == 422
    assert "supports up to" in response.text


def test_nightly_copy_runs_once_a_day_and_rotates(tmp_path):
    db = tmp_path / "printarr.db"
    store = TicketStore(str(db))
    store.init()
    make_ticket(store)
    nightly = backup.NightlyBackup(str(db), store.backup_dir, LONDON, hour=3, keep=2)

    assert nightly.run_once(datetime(2026, 10, 24, 2, 59, tzinfo=LONDON)) is None
    first = nightly.run_once(datetime(2026, 10, 24, 3, 0, tzinfo=LONDON))
    assert first is not None and first.name == "nightly-20261024-030000.db"
    assert nightly.run_once(datetime(2026, 10, 24, 3, 30, tzinfo=LONDON)) is None

    nightly.run_once(datetime(2026, 10, 25, 3, 0, tzinfo=LONDON))
    nightly.run_once(datetime(2026, 10, 26, 3, 0, tzinfo=LONDON))
    kept = sorted(p.name for p in store.backup_dir.glob("nightly-*.db"))
    assert kept == ["nightly-20261025-030000.db", "nightly-20261026-030000.db"]


def test_nightly_copy_is_a_complete_database(tmp_path):
    db = tmp_path / "printarr.db"
    store = TicketStore(str(db))
    store.init()
    make_ticket(store, "one")
    make_ticket(store, "two")
    copy = backup.NightlyBackup(str(db), store.backup_dir, LONDON, hour=0, keep=7).run_once(
        datetime(2026, 10, 24, 0, 0, tzinfo=LONDON)
    )
    assert backup.verify(copy) == migrations.LATEST_VERSION
    assert len(TicketStore(str(copy)).search()) == 2


def test_restore_command_replaces_the_database(settings, tmp_path, monkeypatch, capsys):
    store = TicketStore(settings.db_path)
    store.init()
    make_ticket(store, "from the backup")
    copy = Path(settings.db_path).parent / "copy.db"
    with closing(sqlite3.connect(settings.db_path)) as src:
        backup.snapshot(src, copy)
    make_ticket(store, "newer, to be replaced")

    monkeypatch.setenv("PRINTARR_DB_PATH", settings.db_path)
    monkeypatch.setenv("PRINTARR_PRINTER_MODE", "file")
    monkeypatch.setenv("PRINTARR_OUTPUT_DIR", settings.output_dir)
    assert backup._restore_cli(["restore", str(copy)]) == 0
    assert [t["message"] for t in TicketStore(settings.db_path).search()] == ["from the backup"]
    assert "previous database kept" in capsys.readouterr().out
