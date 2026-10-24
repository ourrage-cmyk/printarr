from dataclasses import replace

from fastapi.testclient import TestClient

import app.alerts as alerts
import app.main
from app.main import create_app


def capture_telegram(monkeypatch):
    sent = []

    def fake_send(token, chat_id, text):
        sent.append(text)

    monkeypatch.setattr(alerts, "send_telegram", fake_send)
    monkeypatch.setattr(app.main, "send_telegram", fake_send)
    return sent


def configure_telegram(client):
    client.put(
        "/api/v1/settings/alerts",
        json={"telegram_token": "123456:SECRETTOKEN-abcd", "telegram_chat_id": "42"},
    )


def test_render_failure_rejects_ticket(settings, monkeypatch):
    import app.main as main

    def broken(*args, **kwargs):
        raise RuntimeError("bad template")

    monkeypatch.setattr(main, "render_lines", broken)
    with TestClient(create_app(settings)) as client:
        response = client.post("/api/v1/tickets", json={"recipient": "yannic", "message": "hi"})
        assert response.status_code == 500
        assert "not queued" in response.json()["detail"]
        assert client.get("/api/v1/tickets").json() == []


def test_model_outage_falls_back_and_alerts_once(settings, monkeypatch):
    sent = capture_telegram(monkeypatch)
    with TestClient(create_app(settings)) as client:
        configure_telegram(client)
        client.put(
            "/api/v1/settings/model",
            json={"enabled": True, "base_url": "http://127.0.0.1:1/v1", "model": "m", "timeout": 1},
        )
        first = client.post("/api/v1/tickets", json={"recipient": "wife", "message": "one"}).json()
        second = client.post("/api/v1/tickets", json={"recipient": "wife", "message": "two"}).json()
        assert first["selection"] == second["selection"] == "rule"
        assert sum("decision model down" in text for text in sent) == 1


def test_printer_outage_alerts_once(settings, monkeypatch):
    sent = capture_telegram(monkeypatch)
    tcp = replace(settings, printer_mode="tcp", printer_host="127.0.0.1", printer_port=1, printer_timeout=1)
    app = create_app(tcp)
    with TestClient(app) as client:
        configure_telegram(client)
        client.post("/api/v1/tickets", json={"recipient": "yannic", "message": "hi"})
        app.state.scheduler.run_once()
        app.state.scheduler.run_once()
        assert sum("printer unreachable" in text for text in sent) == 1


def test_health_is_503_when_printer_down(settings):
    tcp = replace(settings, printer_mode="tcp", printer_host="127.0.0.1", printer_port=1, printer_timeout=1)
    with TestClient(create_app(tcp)) as client:
        response = client.get("/api/v1/health")
        assert response.status_code == 503
        assert response.json()["checks"]["printer"].startswith("unreachable")


def test_health_is_ok_with_file_printer(settings):
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


def test_alert_settings_persist_and_hide_token(settings):
    with TestClient(create_app(settings)) as client:
        configure_telegram(client)
    with TestClient(create_app(settings)) as client:
        body = client.get("/api/v1/settings/alerts").json()
        assert body["telegram_configured"] is True
        assert body["telegram_token_hint"] == "...abcd"
        assert "SECRET" not in str(body)
        assert "kuma_push_url" not in body


def test_test_alert_requires_configuration(settings, monkeypatch):
    capture_telegram(monkeypatch)
    with TestClient(create_app(settings)) as client:
        assert client.post("/api/v1/alerts/test").status_code == 400
        configure_telegram(client)
        assert client.post("/api/v1/alerts/test").json() == {"sent": True}



class StatusTransport:
    """A printer that reports the status bytes we give it."""
    target = "fake"

    def __init__(self, answers):
        self.answers = answers

    def send(self, data):
        pass

    def check(self):
        pass

    def read_status(self):
        return self.answers


def test_paper_cover_and_cutter_faults_alert_once_each(settings, monkeypatch):
    sent = capture_telegram(monkeypatch)
    transport = StatusTransport({2: 0x04, 3: 0x08, 4: 0x60})  # cover open, cutter error, paper end
    app = create_app(settings, transport=transport)
    with TestClient(app) as client:
        configure_telegram(client)
        app.state.watch_printer()
        app.state.watch_printer()
        assert sum("printer cover open" in text for text in sent) == 1
        assert sum("autocutter error" in text for text in sent) == 1
        assert sum("paper out" in text for text in sent) == 1
        health = client.get("/api/v1/health").json()
        assert health["checks"]["paper"] == "fault"


def test_missing_status_answer_raises_no_alert(settings, monkeypatch):
    sent = capture_telegram(monkeypatch)
    app = create_app(settings, transport=StatusTransport({2: None, 3: None, 4: None}))
    with TestClient(app) as client:
        configure_telegram(client)
        app.state.watch_printer()
        assert not any("paper" in text or "cover" in text for text in sent)


def test_telegram_errors_never_show_the_bot_token(monkeypatch):
    import urllib.request

    from app.alerts import send_telegram

    token = "123456:SECRET-TOKEN-VALUE"

    def broken(request, timeout):
        raise OSError(f"cannot reach {request.full_url}")

    monkeypatch.setattr(urllib.request, "urlopen", broken)
    try:
        send_telegram(token, "42", "hi")
    except RuntimeError as exc:
        assert token not in str(exc)
        assert "<token>" in str(exc)
        assert exc.__cause__ is None and exc.__suppress_context__
    else:
        raise AssertionError("expected a RuntimeError")
