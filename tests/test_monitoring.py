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
        client.put("/api/v1/settings/alerts", json={"kuma_push_url": "http://kuma:3001/api/push/abc"})
    with TestClient(create_app(settings)) as client:
        body = client.get("/api/v1/settings/alerts").json()
        assert body["telegram_configured"] is True
        assert body["telegram_token_hint"] == "...abcd"
        assert "SECRET" not in str(body)
        assert body["kuma_push_url"] == "http://kuma:3001/api/push/abc"


def test_test_alert_requires_configuration(settings, monkeypatch):
    capture_telegram(monkeypatch)
    with TestClient(create_app(settings)) as client:
        assert client.post("/api/v1/alerts/test").status_code == 400
        configure_telegram(client)
        assert client.post("/api/v1/alerts/test").json() == {"sent": True}
