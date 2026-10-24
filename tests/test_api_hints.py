"""Every 4xx tells the caller, and an agent reading it, how to fix the request."""

from fastapi.testclient import TestClient

from app.main import create_app


def _client(settings):
    return TestClient(create_app(settings))


def test_missing_field_names_the_field_and_points_to_the_schema(settings):
    with _client(settings) as client:
        response = client.post("/api/v1/tickets/compose", json={"blocks": []})
    body = response.json()
    assert response.status_code == 422
    assert any("recipient" in " ".join(map(str, e["loc"])) for e in body["detail"])
    assert "/openapi.json" in body["hint"] and "/api/v1/blocks" in body["hint"]


def test_delivery_at_without_send_at_gives_an_example(settings):
    body = {"recipient": "yannic", "message": "hi", "delivery": "at"}
    with _client(settings) as client:
        response = client.post("/api/v1/tickets", json=body)
    assert response.status_code == 422
    assert response.json()["detail"] == "delivery at needs send_at"
    assert "send_at" in response.json()["hint"]
    assert response.json()["example"]["send_at"].startswith("2026")


def test_hold_with_send_at_explains_the_two_ways(settings):
    body = {"recipient": "yannic", "message": "hi", "hold": True, "send_at": "2026-10-30T10:00:00"}
    with _client(settings) as client:
        response = client.post("/api/v1/tickets", json=body)
    assert response.status_code == 422
    assert "release" in response.json()["hint"]


def test_compose_block_problem_carries_hint_and_example(settings):
    body = {"recipient": "yannic", "blocks": [{"type": "nope", "mood": "happy", "slots": {}}]}
    with _client(settings) as client:
        response = client.post("/api/v1/tickets/compose", json=body)
    body = response.json()
    assert response.status_code == 422
    assert body["detail"][0]["slot"] == "blocks[0].type"
    assert "GET /api/v1/blocks" in body["hint"]
    assert body["example"]["blocks"][0]["type"] == "greeting"


def test_slot_ticket_on_a_non_slot_template_names_the_slot_templates(settings):
    body = {"recipient": "yannic", "template": 1, "slots": {}}
    with _client(settings) as client:
        response = client.post("/api/v1/tickets/slots", json=body)
    assert response.status_code == 422
    assert "101" in response.json()["hint"] and "102" in response.json()["hint"]

