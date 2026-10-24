"""A slow or failed model never blocks a print, and an alert needs repeated failures."""

import io
import json
import sqlite3
import urllib.error

from app import templates
from app.alerts import Notifier, AlertSettings, describe_failure
from app.config import Settings
from app.migrations import LATEST_VERSION, migrate


def test_default_timeout_covers_a_cold_load_and_models_are_not_pinned():
    assert Settings().llm_timeout == 45.0
    assert not hasattr(templates, "warm_models")  # no warm-up: a pinned model would exhaust the server's memory


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


def test_migrations_raise_the_seeded_timeout_to_45(tmp_path):
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
    assert values["llm_timeout"] == "45" and values["ha_url"] == "http://ha:8123"


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


def test_model_calls_send_no_keep_alive(monkeypatch):
    seen = []

    def fake_urlopen(request, timeout):
        seen.append(json.loads(request.data))
        raise TimeoutError("timed out")

    monkeypatch.setattr(templates.urllib.request, "urlopen", fake_urlopen)
    try:
        templates.SystemOneModel("http://ollama:11434/v1", "d1:latest", timeout=45).scores("yannic", None, "hi")
    except templates.ModelError:
        pass
    templates.OpenAICompatibleModel("http://ollama:11434/v1", "granite4.2:3b", timeout=45)
    try:
        templates.OpenAICompatibleModel("http://ollama:11434/v1", "granite4.2:3b", timeout=45).rewrite("hi")
    except templates.ModelError:
        pass
    assert seen and all("keep_alive" not in body for body in seen)



class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_deadline_hands_out_the_smaller_of_the_limit_and_what_is_left():
    clock = FakeClock()
    deadline = templates.Deadline(50, clock=clock)
    assert deadline.allow(45) == 45
    clock.now = 20
    assert deadline.allow(45) == 30  # 30 s left, so the next call gets 30 s, not 45


def test_an_exhausted_deadline_raises_before_any_call():
    clock = FakeClock()
    deadline = templates.Deadline(50, clock=clock)
    clock.now = 49.5
    try:
        deadline.allow(45)
    except templates.ModelError as exc:
        assert "used up" in str(exc)
    else:
        raise AssertionError("expected the budget to be used up")


def test_the_decision_gets_only_what_the_text_clean_up_left(monkeypatch):
    clock = FakeClock()
    timeouts = []

    def fake_urlopen(request, timeout):
        timeouts.append(timeout)
        raise TimeoutError("timed out")

    monkeypatch.setattr(templates.urllib.request, "urlopen", fake_urlopen)
    deadline = templates.Deadline(50, clock=clock)
    clock.now = 40  # granite took 40 s
    model = templates.SystemOneModel("http://ollama:11434/v1", "d1:latest", timeout=45)
    choice = templates.resolve_choice("yannic", None, "hi", None, model, None, deadline)
    assert choice.selection == "rule"
    assert timeouts == [10]  # 50 s budget less 40 s used


def test_an_exhausted_budget_falls_back_to_rules_without_calling_the_model(monkeypatch):
    clock = FakeClock()
    called = []
    monkeypatch.setattr(templates.urllib.request, "urlopen", lambda *a, **k: called.append(1))
    deadline = templates.Deadline(50, clock=clock)
    clock.now = 50
    model = templates.SystemOneModel("http://ollama:11434/v1", "d1:latest", timeout=45)
    results = []
    choice = templates.resolve_choice("yannic", None, "hi", None, model, results.append, deadline)
    assert choice.selection == "rule" and called == []
    assert results and isinstance(results[0], templates.ModelError)
