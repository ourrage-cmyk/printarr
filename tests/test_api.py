from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from app.escpos import INITIALIZE
from app.main import create_app


def test_create_and_fetch_ticket(settings):
    with TestClient(create_app(settings)) as client:
        created = client.post(
            "/api/v1/tickets",
            json={
                "recipient": "Anna",
                "message": "Dinner at 7",
                "title": "Reminder",
                "send_at": "2026-10-24T19:00:00",
            },
        )
        assert created.status_code == 201
        body = created.json()
        assert body["status"] == "pending"
        assert body["send_at"].startswith("2026-10-24T18:00:00")  # Europe/London is BST

        fetched = client.get(f"/api/v1/tickets/{body['id']}")
        assert fetched.json()["recipient"] == "Anna"


def test_rejects_bad_input(settings):
    with TestClient(create_app(settings)) as client:
        assert client.post("/api/v1/tickets", json={"recipient": "", "message": "x"}).status_code == 422
        extra = {"recipient": "Anna", "message": "x", "copies": 3}
        assert client.post("/api/v1/tickets", json=extra).status_code == 422


def test_scheduler_prints_and_serves_escpos(settings):
    app = create_app(settings)
    with TestClient(app) as client:
        ticket = client.post("/api/v1/tickets", json={"recipient": "Anna", "message": "Hello"}).json()

        assert app.state.scheduler.run_once() == 1

        assert client.get(f"/api/v1/tickets/{ticket['id']}").json()["status"] == "sent"
        assert len(list(Path(settings.output_dir).glob("*.bin"))) == 1

        payload = client.get(f"/api/v1/tickets/{ticket['id']}/escpos").content
        assert payload.startswith(INITIALIZE)
        assert b"Hello" in payload


def test_preview_does_not_queue(settings):
    with TestClient(create_app(settings)) as client:
        preview = client.post(
            "/api/v1/tickets/preview", json={"recipient": "Anna", "message": "Pasta", "sender": "Yannic"}
        )
        assert preview.status_code == 200
        assert "TO: Anna" in preview.json()["text"]
        assert client.get("/api/v1/tickets").json() == []


def test_cancel_and_retry_rules(settings):
    app = create_app(settings)
    with TestClient(app) as client:
        ticket = client.post("/api/v1/tickets", json={"recipient": "Anna", "message": "Hi"}).json()
        assert client.post(f"/api/v1/tickets/{ticket['id']}/cancel").json()["status"] == "cancelled"
        assert client.post(f"/api/v1/tickets/{ticket['id']}/cancel").status_code == 409
        assert client.post(f"/api/v1/tickets/{ticket['id']}/retry").json()["status"] == "pending"
        assert client.post("/api/v1/tickets/nope/cancel").status_code == 404


def test_printer_status_and_test_print(settings):
    with TestClient(create_app(settings)) as client:
        status = client.get("/api/v1/printer").json()
        assert status["mode"] == "file" and status["reachable"] is True
        assert client.post("/api/v1/printer/test").status_code == 200


def test_api_key_is_enforced(settings):
    with TestClient(create_app(replace(settings, api_key="secret"))) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/api/v1/tickets").status_code == 401
        assert client.get("/api/v1/tickets", headers={"X-API-Key": "wrong"}).status_code == 401
        assert client.get("/api/v1/tickets", headers={"X-API-Key": "secret"}).status_code == 200
