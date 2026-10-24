from pathlib import Path

import app.alerts as alerts
import app.main

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
        assert len(templates) == 12  # six per recipient, including the Morning image design


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


def test_auto_is_the_default_template(settings):
    with TestClient(create_app(settings)) as client:
        body = client.post("/api/v1/tickets", json={"recipient": "wife", "message": "Hi"}).json()
        assert body["selection"] == "rule"
        assert body["template_id"] in (4, 5, 6)


def test_held_ticket_is_released_and_prints(settings):
    app = create_app(settings)
    with TestClient(app) as client:
        held = client.post(
            "/api/v1/tickets",
            json={"recipient": "yannic", "message": "Dinner is ready", "hold": True, "hold_key": "user-home"},
        ).json()
        assert held["status"] == "held"
        assert app.state.scheduler.run_once() == 0  # held tickets never print on their own

        released = client.post(f"/api/v1/holds/user-home/release").json()
        assert [t["id"] for t in released] == [held["id"]]
        assert app.state.scheduler.run_once() == 1
        assert client.get(f"/api/v1/tickets/{held['id']}").json()["status"] == "sent"


def test_hold_and_send_at_cannot_be_combined(settings):
    with TestClient(create_app(settings)) as client:
        body = {"recipient": "yannic", "message": "x", "hold": True, "send_at": "2026-10-24T17:30:00"}
        assert client.post("/api/v1/tickets", json=body).status_code == 422


def test_release_single_ticket(settings):
    with TestClient(create_app(settings)) as client:
        held = client.post(
            "/api/v1/tickets", json={"recipient": "yannic", "message": "x", "hold": True}
        ).json()
        assert client.post(f"/api/v1/tickets/{held['id']}/release").json()["status"] == "pending"
        assert client.post(f"/api/v1/tickets/{held['id']}/release").status_code == 409


def test_model_settings_persist_across_restart(settings):
    from dataclasses import replace

    with TestClient(create_app(settings)) as client:
        saved = client.put(
            "/api/v1/settings/model",
            json={"enabled": True, "base_url": "http://ollama:11434/v1", "model": "qwen2.5:3b"},
        ).json()
        assert saved["base_url"] == "http://ollama:11434/v1"

    # A restart with different environment values must keep what was saved in the UI.
    fresh_env = replace(settings, llm_base_url="", llm_model="other")
    with TestClient(create_app(fresh_env)) as client:
        again = client.get("/api/v1/settings/model").json()
        assert again["base_url"] == "http://ollama:11434/v1"
        assert again["model"] == "qwen2.5:3b"


def test_web_ui_is_served(settings):
    with TestClient(create_app(settings)) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "New ticket" in page.text
        assert ">Preview<" in page.text
        for label in ("History", "Inbox", "Insights", "Left by", "Tone"):
            assert label in page.text


def test_render_is_fast_enough_for_instant_print(settings):
    import time

    with TestClient(create_app(settings)) as client:
        client.post("/api/v1/tickets", json={"recipient": "yannic", "message": "warm up"})
        held = client.post(
            "/api/v1/tickets", json={"recipient": "yannic", "message": "Hello " * 50, "hold": True}
        ).json()
        started = time.perf_counter()
        client.post(f"/api/v1/tickets/{held['id']}/release")
        client.app.state.scheduler.run_once()
        elapsed = time.perf_counter() - started
        assert elapsed < 1.0


def test_formatted_is_the_default_and_is_sent_as_is(settings):
    with TestClient(create_app(settings)) as client:
        body = client.post(
            "/api/v1/tickets", json={"recipient": "yannic", "message": "teh  dinner"}
        ).json()
        assert body["text_state"] == "formatted"
        assert body["message"] == "teh  dinner"


def test_unformatted_text_is_cleaned_by_the_text_model(settings, monkeypatch):
    from app import templates

    monkeypatch.setattr(templates.OpenAICompatibleModel, "rewrite", lambda self, text, deadline=None: "Dinner is ready.")
    with TestClient(create_app(settings)) as client:
        client.put(
            "/api/v1/settings/model",
            json={"enabled": True, "base_url": "http://ollama:11434/v1", "text_model": "granite4.2:3b"},
        )
        body = client.post(
            "/api/v1/tickets",
            json={"recipient": "yannic", "message": "um dinner is ready", "text_state": "unformatted"},
        ).json()
        assert body["text_state"] == "unformatted"
        assert body["message"] == "Dinner is ready."


def test_unformatted_text_is_sent_as_is_when_text_model_is_down(settings, monkeypatch):
    sent = []
    monkeypatch.setattr(alerts, "send_telegram", lambda t, c, text: sent.append(text))
    monkeypatch.setattr(app.main, "send_telegram", lambda t, c, text: sent.append(text))
    with TestClient(create_app(settings)) as client:
        client.put("/api/v1/settings/alerts", json={"telegram_token": "1:abcd", "telegram_chat_id": "9"})
        client.put(
            "/api/v1/settings/model",
            json={"enabled": True, "base_url": "http://127.0.0.1:1/v1", "timeout": 1},
        )
        for _ in range(3):  # an alert needs repeated failures
            body = client.post(
                "/api/v1/tickets",
                json={"recipient": "yannic", "message": "um dinner", "text_state": "unformatted"},
            ).json()
            assert body["message"] == "um dinner"  # printed as sent every time
        assert any("text model failed" in text for text in sent)


def test_a_held_ticket_can_be_cancelled(settings):
    with TestClient(create_app(settings)) as client:
        held = client.post("/api/v1/tickets", json={"recipient": "yannic", "message": "wait", "template": 3, "hold": True}).json()
        cancelled = client.post(f"/api/v1/tickets/{held['id']}/cancel")
        assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"


def test_since_hours_has_an_upper_bound(settings):
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/log", params={"since_hours": 10**17}).status_code == 422
        assert client.get("/api/v1/log/summary", params={"since_hours": 10**17}).status_code == 422
        assert client.get("/api/v1/log", params={"since_hours": 24}).status_code == 200


def test_web_ui_offers_no_single_release_for_pile_tickets(settings):
    with TestClient(create_app(settings)) as client:
        html = client.get("/").text
        assert "t.delivery !== 'on_release'" in html
