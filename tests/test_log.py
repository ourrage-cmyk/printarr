import sqlite3

from fastapi.testclient import TestClient

from app.main import create_app
from app.store import TicketStore


def test_old_database_gets_the_new_columns(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE tickets (id TEXT PRIMARY KEY, recipient TEXT NOT NULL, sender TEXT, title TEXT, "
            "message TEXT NOT NULL, status TEXT NOT NULL, hold_key TEXT, send_at_ms INTEGER NOT NULL, "
            "next_attempt_ms INTEGER NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT, "
            "template_id INTEGER NOT NULL, text_state TEXT NOT NULL DEFAULT 'formatted', "
            "blocks_json TEXT NOT NULL DEFAULT '[]', decorations TEXT NOT NULL DEFAULT '', "
            "selection TEXT NOT NULL, created_at_ms INTEGER NOT NULL, updated_at_ms INTEGER NOT NULL, "
            "printed_at_ms INTEGER)"
        )
    TicketStore(str(path)).init()
    with sqlite3.connect(path) as conn:
        names = {row[1] for row in conn.execute("PRAGMA table_info(tickets)")}
    assert {"kind", "tone", "from_user", "to_user", "inbox_state", "render_ms", "print_ms"} <= names


def test_ticket_carries_kind_tone_and_an_inbox_state(settings):
    app = create_app(settings)
    with TestClient(app) as client:
        note = client.post(
            "/api/v1/tickets",
            json={"recipient": "wife", "message": "Hi", "kind": "shopping", "tone": "playful"},
        ).json()
        assert (note["kind"], note["tone"], note["inbox_state"]) == ("shopping", "playful", None)
        assert note["render_ms"] is not None and note["choice_source"] == "rule"

        inbox = client.post(
            "/api/v1/tickets",
            json={"recipient": "wife", "message": "Dinner at 7", "from_user": "yannic", "to_user": "wife"},
        ).json()
        assert (inbox["from_user"], inbox["to_user"], inbox["inbox_state"]) == ("yannic", "wife", "unread")
        assert inbox["kind"] == "note" and inbox["tone"] == "neutral"


def test_log_filters_summary_and_export(settings):
    app = create_app(settings)
    with TestClient(app) as client:
        client.post("/api/v1/tickets", json={"recipient": "wife", "message": "a", "kind": "todo"})
        client.post("/api/v1/tickets", json={"recipient": "wife", "message": "b", "kind": "todo", "tone": "firm"})
        client.post("/api/v1/tickets", json={"recipient": "yannic", "message": "c", "kind": "fun"})

        todo = client.get("/api/v1/log", params={"kind": "todo"}).json()
        assert [t["message"] for t in todo] == ["a", "b"]  # oldest first
        assert client.get("/api/v1/log", params={"recipient": "yannic", "tone": "firm"}).json() == []

        summary = client.get("/api/v1/log/summary").json()
        assert summary["by_kind"] == {"todo": 2, "fun": 1}
        assert summary["by_tone"]["firm"] == 1
        assert summary["by_status"]["pending"] == 3

        csv_text = client.get("/api/v1/log/export", params={"recipient": "wife"}).text
        lines = csv_text.strip().splitlines()
        assert lines[0].startswith("id,created_at,recipient")
        assert len(lines) == 3 and ",todo," in lines[1]

        as_json = client.get("/api/v1/log/export", params={"format": "json"}).json()
        assert len(as_json) == 3


def test_log_cannot_group_by_message_text(settings):
    import pytest

    store = TicketStore(settings.db_path)
    store.init()
    with pytest.raises(ValueError):
        store.log_counts("message")
