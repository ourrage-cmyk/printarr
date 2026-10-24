"""A slow or failed model never blocks a print, and an alert needs repeated failures."""

import io
import json
import sqlite3
import urllib.error

from app import templates
from app.alerts import Notifier, AlertSettings, describe_failure
from app.config import Settings
from app.migrations import LATEST_VERSION, migrate


def test_default_timeout_covers_a_cold_d1_load():
    assert Settings().llm_timeout == 30.0


def test_describe_failure_names_the_cause():
    assert describe_failure(TimeoutError("timed out"), "the decision model", 30.0) == \
        "the decision model gave no answer within 30 s (timeout)"
    http = urllib.error.HTTPError("http://x/v1/systemone", 404, "Not Found", {}, io.BytesIO(b"no such model"))
    assert describe_failure(http, "the decision model") == "the decision model answered HTTP 404 Not Found: no such model"
    unreachable = urllib.error.URLError(ConnectionRefusedError("refused"))
    assert "cannot be reached" in describe_failure(unreachable, "the text model")


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _notifier(sent: list[str], clock: Clock) -> Notifier:
    settings = AlertSettings(telegram_token="1:abc", telegram_chat_id="9")
    return Notifier(lambda: settings, sender=lambda token, chat, text: sent.append(text), clock=clock)


def test_two_failures_are_logged_and_the_third_alerts_once():
    sent: list[str] = []
    clock = Clock()
    notifier = _notifier(sent, clock)
    notifier.repeated("model", "decision model failed: timeout")
    notifier.repeated("model", "decision model failed: timeout")
    assert sent == []
    notifier.repeated("model", "decision model failed: timeout")
    notifier.repeated("model", "decision model failed: timeout")
    assert len(sent) == 1 and "decision model failed" in sent[0]


def test_failures_outside_the_window_do_not_add_up():
    sent: list[str] = []
    clock = Clock()
    notifier = _notifier(sent, clock)
    notifier.repeated("model", "x")
    notifier.repeated("model", "x")
    clock.now += 1000  # past the 15-minute window
    notifier.repeated("model", "x")
    assert sent == []


def test_a_success_clears_the_count():
    sent: list[str] = []
    clock = Clock()
    notifier = _notifier(sent, clock)
    notifier.repeated("model", "x")
    notifier.repeated("model", "x")
    notifier.clear_failures("model")
    notifier.repeated("model", "x")
    assert sent == []


def test_migration_seven_raises_the_seeded_five_second_timeout(tmp_path):
    conn = sqlite3.connect(tmp_path / "db.sqlite", isolation_level=None)
    conn.row_factory = sqlite3.Row
    migrate(conn)
    conn.execute("PRAGMA user_version = 6")
    conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO settings VALUES ('llm_timeout', '5.0')")
    conn.execute("INSERT INTO settings VALUES ('ha_url', 'http://ha:8123')")
    migrate(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == LATEST_VERSION
    values = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM settings")}
    assert values["llm_timeout"] == "30" and values["ha_url"] == "http://ha:8123"


def test_a_value_chosen_by_hand_is_kept_by_the_migration(tmp_path):
    conn = sqlite3.connect(tmp_path / "db.sqlite", isolation_level=None)
    conn.row_factory = sqlite3.Row
    migrate(conn)
    conn.execute("PRAGMA user_version = 6")
    conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO settings VALUES ('llm_timeout', '12')")
    migrate(conn)
    assert conn.execute("SELECT value FROM settings WHERE key = 'llm_timeout'").fetchone()[0] == "12"


def test_granite_gets_a_token_budget_and_its_errors_are_described(monkeypatch):
    seen = {}

    def fake_urlopen(request, timeout):
        seen["body"] = json.loads(request.data)
        raise TimeoutError("timed out")

    monkeypatch.setattr(templates.urllib.request, "urlopen", fake_urlopen)
    model = templates.OpenAICompatibleModel("http://ollama:11434/v1", "granite4.2:3b", timeout=30)
    try:
        model.rewrite("um dinner")
    except templates.ModelError as exc:
        assert "gave no answer within 30 s" in str(exc) and "granite4.2:3b" in str(exc)
    else:
        raise AssertionError("expected a ModelError")
    assert seen["body"]["max_tokens"] == 1024


def test_warm_up_loads_d1_through_systemone_and_granite_natively(monkeypatch):
    calls = []

    class Done:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b"{}"

    def fake_urlopen(request, timeout):
        calls.append((request.full_url, json.loads(request.data)))
        return Done()

    monkeypatch.setattr(templates.urllib.request, "urlopen", fake_urlopen)
    failed = templates.warm_models("http://ollama:11434/v1", "d1:latest", "granite4.2:3b", timeout=30)
    assert failed == []
    urls = {url: payload for url, payload in calls}
    assert "http://ollama:11434/v1/systemone" in urls
    assert urls["http://ollama:11434/api/generate"]["keep_alive"] == "30m"
    assert "images" not in urls["http://ollama:11434/v1/systemone"]
