"""DLE EOT decoding, checked against the bit layouts in the Command Reference (dle_eot)."""

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

import app.alerts as alerts
import app.main as main
from app.main import create_app
from app.status import decode

IDLE = {1: 0x12, 2: 0x12, 3: 0x12, 4: 0x12}  # idle, online, no errors


def test_idle_bytes_have_no_faults():
    status = decode(IDLE)
    assert status.faults == frozenset()
    assert status.warnings == frozenset()
    assert status.blocking is False
    assert status.known == frozenset({"offline", "cover", "error", "recoverable", "cutter",
                                      "unrecoverable", "auto_recoverable", "paper", "paper_near_end"})


@pytest.mark.parametrize(
    "answers, fault",
    [
        ({1: 0x12 | 0x08}, "offline"),
        ({2: 0x12 | 0x04}, "cover"),
        ({2: 0x12 | 0x40}, "error"),
        ({2: 0x12 | 0x20}, "paper"),          # paper-end stop
        ({3: 0x12 | 0x04}, "recoverable"),
        ({3: 0x12 | 0x08}, "cutter"),
        ({3: 0x12 | 0x20}, "unrecoverable"),
        ({3: 0x12 | 0x40}, "auto_recoverable"),
        ({4: 0x12 | 0x60}, "paper"),          # paper end sensor, paper not present
    ],
)
def test_each_fault_bit(answers, fault):
    status = decode({**IDLE, **answers})
    assert status.faults == frozenset({fault})
    assert status.blocking is True


def test_near_end_is_a_warning_not_a_fault():
    status = decode({**IDLE, 4: 0x12 | 0x0C})
    assert status.warnings == frozenset({"paper_near_end"})
    assert status.blocking is False


def test_missing_answers_are_not_known():
    status = decode({1: 0x12, 2: None, 3: None, 4: None})
    assert "offline" in status.known
    assert "cover" not in status.known
    assert "paper" not in status.known
    assert status.faults == frozenset()


def test_paper_fault_needs_both_sensors_known_to_clear():
    assert "paper" not in decode({2: 0x12, 4: None}).known


class StatusTransport:
    target = "fake"

    def __init__(self, answers):
        self.answers = answers

    def send(self, data):
        pass

    def check(self):
        pass

    def read_status(self):
        return self.answers


@pytest.fixture
def sent(monkeypatch):
    messages = []
    monkeypatch.setattr(alerts, "send_telegram", lambda token, chat, text: messages.append(text))
    monkeypatch.setattr(main, "send_telegram", lambda token, chat, text: messages.append(text))
    return messages


def configure(client):
    client.put("/api/v1/settings/alerts",
               json={"telegram_token": "123456:SECRETTOKEN-abcd", "telegram_chat_id": "42"})


def test_offline_and_unrecoverable_alert_once_then_recover(settings, sent):
    transport = StatusTransport({1: 0x12 | 0x08, 2: 0x12, 3: 0x12 | 0x20, 4: 0x12})
    app = create_app(settings, transport=transport)
    with TestClient(app) as client:
        configure(client)
        app.state.watch_printer()
        app.state.watch_printer()
        assert sum("printer offline" in t for t in sent) == 1
        assert sum("unrecoverable error" in t for t in sent) == 1
        assert client.get("/api/v1/health").json()["checks"]["offline"] == "fault"

        transport.answers = {1: 0x12, 2: 0x12, 3: 0x12, 4: 0x12}
        app.state.watch_printer()
        assert any(t == "Printarr recovered: printer offline cleared" for t in sent)
        assert client.get("/api/v1/health").json()["checks"]["offline"] == "ok"


def test_near_end_shows_in_health_without_alert(settings, sent):
    app = create_app(settings, transport=StatusTransport({1: 0x12, 2: 0x12, 3: 0x12, 4: 0x12 | 0x0C}))
    with TestClient(app) as client:
        configure(client)
        app.state.watch_printer()
        assert client.get("/api/v1/health").json()["checks"]["paper_near_end"] == "warning"
        assert not any("near end" in t for t in sent)
