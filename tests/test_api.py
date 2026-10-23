from pathlib import Path

from fastapi.testclient import TestClient

from app.escpos import INITIALIZE
from app.main import create_app


def test_create_and_fetch_ticket(settings):
    with TestClient(create_app(settings)) as client:
        created = client.post(
            "/api/v1/tickets",
            json={
                "recipient": "yannic",
                "message": "Dinner at 7",
                "title": "Reminder",
                "template": 3,
                "send_at": "2026-10-24T17:30:00",
            },
        )
        assert created.status_code == 201
        body = created.json()
        assert body["status"] == "pending"
        assert body["template_id"] == 3
        assert body["selection"] == "explicit"
        assert body["send_at"].startswith("2026-10-24T16:30:00")  # Europe/London is BST

        fetched = client.get(f"/api/v1/tickets/{body['id']}")
        assert fetched.json()["recipient"] == "yannic"


def test_rejects_bad_input(settings):
    with TestClient(create_app(settings)) as client:
        bad_recipient = {"recipient": "Anna", "message": "x"}
        assert client.post("/api/v1/tickets", json=bad_recipient).status_code == 422
        extra = {"recipient": "yannic", "message": "x", "copies": 3}
        assert client.post("/api/v1/tickets", json=extra).status_code == 422


def test_template_must_belong_to_recipient(settings):
    with TestClient(create_app(settings)) as client:
        # Template 4 belongs to the wife's group.
        response = client.post(
            "/api/v1/tickets", json={"recipient": "yannic", "message": "Hi", "template": 4}
        )
        assert response.status_code == 422


def test_rule_fallback_without_model(settings):
    with TestClient(create_app(settings)) as client:
        body = client.post("/api/v1/tickets", json={"recipient": "wife", "message": "Hi"}).json()
        assert body["selection"] == "rule"
        assert body["template_id"] in (4, 5, 6)


def test_templates_endpoint_lists_groups(settings):
    with TestClient(create_app(settings)) as client:
        templates = client.get("/api/v1/templates").json()
        assert {t["recipient"] for t in templates} == {"yannic", "wife"}
        assert len(templates) == 6


def test_scheduler_prints_and_serves_escpos(settings):
    app = create_app(settings)
    with TestClient(app) as client:
        ticket = client.post(
            "/api/v1/tickets", json={"recipient": "yannic", "message": "Hello"}
        ).json()

        assert app.state.scheduler.run_once() == 1

        assert client.get(f"/api/v1/tickets/{ticket['id']}").json()["status"] == "sent"
        assert len(list(Path(settings.output_dir).glob("*.bin"))) == 1

        payload = client.get(f"/api/v1/tickets/{ticket['id']}/escpos").content
        assert payload.startswith(INITIALIZE)
        assert b"Hello" in payload


def test_preview_does_not_queue(settings):
    with TestClient(create_app(settings)) as client:
        preview = client.post(
            "/api/v1/tickets/preview",
            json={"recipient": "yannic", "message": "Pasta", "sender": "home-assistant"},
        )
        assert preview.status_code == 200
        body = preview.json()
        assert "TO: Yannic" in body["text"]
        assert body["width"] == 42
        assert client.get("/api/v1/tickets").json() == []


def test_cancel_and_retry_rules(settings):
    app = create_app(settings)
    with TestClient(app) as client:
        ticket = client.post("/api/v1/tickets", json={"recipient": "yannic", "message": "Hi"}).json()
        assert client.post(f"/api/v1/tickets/{ticket['id']}/cancel").json()["status"] == "cancelled"
        assert client.post(f"/api/v1/tickets/{ticket['id']}/cancel").status_code == 409
        assert client.post(f"/api/v1/tickets/{ticket['id']}/retry").json()["status"] == "pending"
        assert client.post("/api/v1/tickets/nope/cancel").status_code == 404


def test_printer_status_and_test_print(settings):
    with TestClient(create_app(settings)) as client:
        status = client.get("/api/v1/printer").json()
        assert status["mode"] == "file" and status["reachable"] is True
        assert client.post("/api/v1/printer/test").status_code == 200


def test_no_authentication_needed(settings):
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/tickets").status_code == 200
