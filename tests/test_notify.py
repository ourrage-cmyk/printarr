"""POST /api/v1/notify: a Telegram ping for threads, one per caller per minute, token never shown."""

import pytest
from fastapi.testclient import TestClient

from app import main
from app.main import create_app
from app.notify import NotifyLimiter, clean_text
from app.store import TicketStore

TOKEN = "123456:SECRET-TOKEN-VALUE"


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def configured(settings):
    store = TicketStore(settings.db_path)
    store.init()
    store.set_setting("alert_telegram_token", TOKEN)
    store.set_setting("alert_telegram_chat_id", "42")
    return settings


def test_limiter_allows_one_per_source_per_interval():
    clock = FakeClock()
    limiter = NotifyLimiter(interval=60, clock=clock)
    assert limiter.check("a") == 0
    assert limiter.check("a") == pytest.approx(60)
    assert limiter.check("b") == 0  # another source has its own turn
    clock.now += 60
    assert limiter.check("a") == 0


def test_clean_text_drops_control_characters():
    assert clean_text("hi\x00 there\x1b[2J\nnext") == "hi there[2J\nnext"


def test_not_configured_says_how_to_fix_it(settings):
    with TestClient(create_app(settings)) as client:
        reply = client.post("/api/v1/notify", json={"text": "restart please"})
        assert reply.status_code == 400
        assert "PUT /api/v1/settings/alerts" in reply.json()["hint"]


def test_sends_once_then_limits_the_caller(configured, monkeypatch):
    sent = []
    monkeypatch.setattr(main, "send_telegram", lambda token, chat, text: sent.append((token, chat, text)))
    with TestClient(create_app(configured)) as client:
        first = client.post("/api/v1/notify", json={"text": "Please restart onto build 79."})
        assert first.status_code == 200 and first.json() == {"sent": True}
        assert sent == [(TOKEN, "42", "Please restart onto build 79.")]

        second = client.post("/api/v1/notify", json={"text": "again"})
        assert second.status_code == 429
        assert int(second.headers["retry-after"]) >= 1
        assert len(sent) == 1


def test_rejects_extra_fields_and_long_text(configured, monkeypatch):
    monkeypatch.setattr(main, "send_telegram", lambda *args: None)
    with TestClient(create_app(configured)) as client:
        assert client.post("/api/v1/notify", json={"text": "x", "chat_id": "1"}).status_code == 422
        assert client.post("/api/v1/notify", json={"text": "x" * 1001}).status_code == 422


def test_failed_send_does_not_show_the_token(configured, monkeypatch):
    def failing(token, chat, text):
        raise RuntimeError(f"Telegram send failed: https://api.telegram.org/bot{token}/sendMessage 404")

    monkeypatch.setattr(main, "send_telegram", failing)
    with TestClient(create_app(configured)) as client:
        reply = client.post("/api/v1/notify", json={"text": "ping"})
        assert reply.status_code == 502
        assert TOKEN not in reply.text
        assert "SECRET" not in reply.text
