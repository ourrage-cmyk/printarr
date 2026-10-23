from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

import app.ha as ha
from app.blocks import GRAPH_HEIGHT, GRAPH_WIDTH, sparkline_bitmap
from app.escpos import GS, encode
from app.ha import HAError
from app.main import create_app
from app.receipt import Line


def stub_ha(monkeypatch, state="21.5", history=None, error=None):
    def fake_state(self, entity_id):
        if error:
            raise error
        return state

    def fake_history(self, entity_id, hours):
        if error:
            raise error
        return history if history is not None else [18.0, 19.5, 21.0, 20.5, 21.5]

    monkeypatch.setattr(ha.HAClient, "state", fake_state)
    monkeypatch.setattr(ha.HAClient, "numeric_history", fake_history)


def configure_ha(client):
    client.put("/api/v1/settings/ha", json={"url": "http://ha.local:8123", "token": "abcdsecret1234"})


def test_sparkline_bitmap_has_the_printable_size_and_draws_pixels():
    data = sparkline_bitmap([1.0, 5.0, 3.0, 9.0])
    assert len(data) == (GRAPH_WIDTH // 8) * GRAPH_HEIGHT
    assert any(byte for byte in data)


def test_sparkline_needs_two_points():
    with pytest.raises(HAError):
        sparkline_bitmap([1.0])


def test_raster_line_encodes_gs_v0_header():
    line = Line("", raster=(64, 2, b"\xff" * 128))
    payload = encode([line])
    assert GS + b"v0\x00" + bytes([64, 0, 2, 0]) in payload


def test_value_and_sparkline_blocks_are_stored_and_printed(settings, monkeypatch):
    stub_ha(monkeypatch)
    app = create_app(settings)
    with TestClient(app) as client:
        configure_ha(client)
        ticket = client.post(
            "/api/v1/tickets",
            json={
                "recipient": "yannic",
                "message": "Living room",
                "blocks": [
                    {"type": "value", "entity_id": "sensor.living_room_temperature", "label": "Living room", "unit": "°C"},
                    {"type": "sparkline", "entity_id": "sensor.living_room_temperature", "label": "Temperature", "hours": 24},
                ],
            },
        )
        assert ticket.status_code == 201
        preview = client.get(f"/api/v1/tickets/{ticket.json()['id']}/preview").text
        assert "Living room: 21.5 °C" in preview
        assert "[graph]" in preview
        assert app.state.scheduler.run_once() == 1
        payload = client.get(f"/api/v1/tickets/{ticket.json()['id']}/escpos").content
        assert GS + b"v0" in payload


def test_home_assistant_down_at_print_time_prints_a_placeholder_and_alerts(settings, monkeypatch):
    import app.alerts as alerts
    import app.main as main

    sent = []
    monkeypatch.setattr(alerts, "send_telegram", lambda t, c, text: sent.append(text))
    monkeypatch.setattr(main, "send_telegram", lambda t, c, text: sent.append(text))
    stub_ha(monkeypatch, error=HAError("Home Assistant unreachable"))
    app = create_app(settings)
    with TestClient(app) as client:
        configure_ha(client)
        client.put("/api/v1/settings/alerts", json={"telegram_token": "1:abcd", "telegram_chat_id": "9"})
        ticket = client.post(
            "/api/v1/tickets",
            json={"recipient": "yannic", "message": "x", "blocks": [{"type": "value", "entity_id": "sensor.a", "label": "A"}]},
        )
        assert ticket.status_code == 201  # queued: the data is fetched at print time
        assert app.state.scheduler.run_once() == 1
        assert client.get(f"/api/v1/tickets/{ticket.json()['id']}").json()["status"] == "sent"
        assert any("Home Assistant unavailable" in text for text in sent)


def test_unreachable_home_assistant_at_request_time_is_a_clear_error(settings, monkeypatch):
    stub_ha(monkeypatch, error=HAError("Home Assistant unreachable"))
    with TestClient(create_app(settings)) as client:
        configure_ha(client)
        response = client.post(
            "/api/v1/tickets/preview",
            json={"recipient": "yannic", "message": "x", "blocks": [{"type": "value", "entity_id": "sensor.a", "label": "A"}]},
        )
        assert response.status_code == 502
        assert "unreachable" in response.json()["detail"]


def test_ha_token_is_never_returned_in_full(settings):
    with TestClient(create_app(settings)) as client:
        configure_ha(client)
        body = client.get("/api/v1/settings/ha").json()
        assert body["token_configured"] is True
        assert body["token_hint"] == "...1234"
        assert "abcdsecret" not in str(body)


def test_invalid_entity_id_is_rejected(settings):
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/v1/tickets",
            json={"recipient": "yannic", "message": "x", "blocks": [{"type": "value", "entity_id": "Not Valid", "label": "A"}]},
        )
        assert response.status_code == 422
