"""Replays the request bodies the Home Assistant automations send, in the order they fire.

These mirror docs/integrations/home-assistant: the morning and evening briefings are created as
on_release and released straight after, messages wait in the recipient's pile, and standalone
items print at once. Blocks are left out because no Home Assistant is configured in tests.
"""

import dataclasses

from fastapi.testclient import TestClient

from app.main import create_app
from app.store import TicketStore
from tests.test_strips import Recorder

DAY = "2026-10-26"


def make(settings):
    settings = dataclasses.replace(settings, scheduler_enabled=False)
    transport = Recorder()
    return create_app(settings, transport=transport), transport


def morning_briefing(person: str) -> dict:
    # printarr_create_slot_ticket with template 101, as the morning unplug automation renders it.
    return {
        "template": 101,
        "recipient": person,
        "sender": "home-assistant",
        "kind": "morning",
        "tone": "neutral",
        "slots": {"title": "Morning"},
        "delivery": "on_release",
        "idempotency_key": f"morning:{person}:{DAY}",
        "from_user": None,
    }


def release(person: str, trigger: str) -> dict:
    # printarr_release_person renders {"trigger": "..."}
    return {"trigger": trigger}


def test_morning_unplug_prints_one_strip_and_a_repeat_prints_nothing(settings):
    app, transport = make(settings)
    with TestClient(app) as client:
        first = client.post("/api/v1/tickets/slots", json=morning_briefing("yannic"))
        assert first.status_code == 201 and first.json()["status"] == "held"
        result = client.post("/api/v1/people/yannic/release", json=release("yannic", "morning")).json()
        assert len(result["strips"]) == 1 and len(transport.payloads) == 1

        # The phone is unplugged twice. The briefing key returns the printed ticket, not a new one.
        again = client.post("/api/v1/tickets/slots", json=morning_briefing("yannic"))
        assert again.json()["id"] == first.json()["id"]
        second = client.post("/api/v1/people/yannic/release", json=release("yannic", "morning")).json()
        assert second["strips"] == [] and len(transport.payloads) == 1


def test_message_for_allyson_waits_for_her_strip_only(settings):
    app, transport = make(settings)
    with TestClient(app) as client:
        note = {
            "recipient": "wife", "from_user": "yannic", "to_user": "wife", "kind": "note",
            "tone": "loving", "message": "Dinner is at seven.", "delivery": "on_release",
            "idempotency_key": f"message:yannic:wife:{DAY}:dinner", "sender": "home-assistant",
        }
        queued = client.post("/api/v1/tickets", json=note).json()
        assert queued["status"] == "held" and queued["inbox_state"] == "unread"

        # Yannic's own strip prints nothing of Allyson's message.
        assert client.post("/api/v1/people/yannic/release", json=release("yannic", "evening")).json()["strips"] == []
        assert transport.payloads == []

        strips = client.post("/api/v1/people/wife/release", json=release("wife", "arrival")).json()["strips"]
        assert [s["ticket_ids"] for s in strips] == [[queued["id"]]]
        assert len(transport.payloads) == 1


def test_evening_arrival_prints_the_rundown_and_waiting_messages(settings):
    app, transport = make(settings)
    with TestClient(app) as client:
        client.post("/api/v1/tickets", json={
            "recipient": "yannic", "from_user": "wife", "to_user": "yannic", "kind": "note",
            "message": "Bins are out.", "delivery": "on_release", "sender": "home-assistant",
        })
        evening = {**morning_briefing("yannic"), "kind": "evening", "slots": {"title": "Evening"},
                   "idempotency_key": f"evening:yannic:{DAY}"}
        client.post("/api/v1/tickets/slots", json=evening)
        result = client.post("/api/v1/people/yannic/release", json=release("yannic", "evening")).json()
        # The evening rundown opens with a greeting, so it starts a new strip: the waiting note goes first.
        assert [len(strip["ticket_ids"]) for strip in result["strips"]] == [1, 1]


def test_shopping_list_prints_at_once_and_stays_off_the_pile(settings):
    app, transport = make(settings)
    with TestClient(app) as client:
        shopping = client.post("/api/v1/tickets", json={
            "recipient": "yannic", "kind": "shopping", "title": "Shopping",
            "message": "Milk\nBread", "delivery": "now", "sender": "home-assistant",
        }).json()
        assert shopping["status"] in ("pending", "sent")
        assert client.post("/api/v1/people/yannic/release", json=release("yannic", "request")).json()["strips"] == []
        assert app.state.scheduler.run_once() == 1
        assert TicketStore(settings.db_path).get(shopping["id"])["status"] == "sent"


def test_scheduled_note_prints_at_its_time_not_in_the_pile(settings):
    app, transport = make(settings)
    with TestClient(app) as client:
        note = client.post("/api/v1/tickets", json={
            "recipient": "wife", "kind": "reminder", "message": "Hey, I love your message.",
            "delivery": "at", "send_at": "2026-10-26T15:00:00", "sender": "hermes",
        })
        assert note.status_code == 201
        assert client.post("/api/v1/people/wife/release", json=release("wife", "request")).json()["strips"] == []
