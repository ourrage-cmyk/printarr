from fastapi.testclient import TestClient

from app.main import create_app
from app.slots import Metric, NoteSlots, fetch_values, slot_lines, validate, SlotProblems
from app.ha import HAError


class FakeClient:
    def __init__(self, states):
        self.states = states

    def state(self, entity_id):
        if entity_id not in self.states:
            raise HAError(f"{entity_id}: not found")
        return self.states[entity_id]


def texts(lines):
    return [line.text for line in lines]


def test_schema_lists_slot_names_and_limits(settings):
    with TestClient(create_app(settings)) as client:
        schema = client.get("/api/v1/templates/101/schema").json()
        assert {"greeting", "title", "metrics", "paragraph", "formatted", "tip"} <= set(schema["properties"])
        assert schema["properties"]["metrics"]["maxItems"] == 4
        assert client.get("/api/v1/templates/1/schema").status_code == 404
        listed = client.get("/api/v1/slot-templates").json()
        assert [t["id"] for t in listed] == [101, 102]


def test_bare_briefing_is_a_morning_ticket_with_choice_and_timing(settings):
    with TestClient(create_app(settings)) as client:
        ticket = client.post("/api/v1/tickets/slots", json={"template": 101, "recipient": "yannic"}).json()
    assert ticket["template_id"] == 101 and ticket["kind"] == "morning"
    assert ticket["choice_source"] == "explicit" and ticket["render_ms"] is not None


def test_slots_are_stored_with_the_ticket(settings):
    import json

    from app.store import TicketStore

    with TestClient(create_app(settings)) as client:
        ticket = client.post(
            "/api/v1/tickets/slots",
            json={"template": 101, "recipient": "yannic", "slots": {"title": "Today", "paragraph": "Quiet day."}},
        ).json()
    stored = TicketStore(settings.db_path).get(ticket["id"])
    filled = json.loads(stored["slots_json"])
    assert filled["title"] == "Today" and filled["paragraph"] == "Quiet day."
    assert len(filled["metrics"]) == 4  # defaults for Yannic
    assert filled["greeting"].startswith("Good ")
    assert filled["tip"]


def test_wife_briefing_has_no_default_metrics(settings):
    import json

    from app.store import TicketStore

    with TestClient(create_app(settings)) as client:
        ticket = client.post("/api/v1/tickets/slots", json={"template": 101, "recipient": "wife"}).json()
    assert not json.loads(TicketStore(settings.db_path).get(ticket["id"])["slots_json"]).get("metrics")


def test_bad_slots_return_422_listing_each_problem(settings):
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/v1/tickets/slots",
            json={
                "template": 101,
                "recipient": "yannic",
                "slots": {
                    "colour": "red",
                    "metrics": [{"label": "X", "entity_id": "sensor.a", "value": 3}],
                },
            },
        )
        assert response.status_code == 422
        slots = [p["slot"] for p in response.json()["detail"]]
        assert "colour" in slots and "metrics.0" in slots


def test_note_needs_a_paragraph(settings):
    with TestClient(create_app(settings)) as client:
        response = client.post("/api/v1/tickets/slots", json={"template": 102, "recipient": "wife", "slots": {}})
        assert response.status_code == 422
        ok = client.post(
            "/api/v1/tickets/slots",
            json={"template": 102, "recipient": "wife", "slots": {"paragraph": "Dinner at seven."}},
        )
        assert ok.status_code == 201


def test_metric_needs_exactly_one_source():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Metric(label="A")
    with pytest.raises(ValidationError):
        Metric(label="A", value=1, series=[1, 2])
    assert Metric(label="A", series=[1, 2]).series == [1, 2]


def test_validate_names_the_slot_that_failed():
    import pytest

    with pytest.raises(SlotProblems) as caught:
        validate(102, {"paragraph": ""})
    assert caught.value.problems[0]["slot"] == "paragraph"


def test_entity_metrics_read_home_assistant_and_missing_ones_print_dashes():
    slots = {
        "metrics": [
            {"label": "steps", "entity_id": "sensor.total_steps"},
            {"label": "stress", "entity_id": "sensor.avg_stress_level", "unit": "%"},
            {"label": "load", "value": 3.5},
        ]
    }
    fetched = fetch_values(slots, FakeClient({"sensor.total_steps": "6120"}))
    assert fetched == ["6120", None, None]
    lines = texts(slot_lines(slots, fetched))
    assert lines[0].startswith("STEPS") and lines[0].endswith("6120")
    assert lines[1].startswith("STRESS") and lines[1].endswith("--%")
    assert lines[2].endswith("3.5")


def test_literal_series_shows_its_last_value_and_paragraph_wraps():
    lines = texts(slot_lines({"paragraph": "word " * 30, "metrics": [{"label": "x", "series": [1, 2, 9]}]}))
    assert lines[0].endswith("9")
    assert len(lines) > 3 and all(len(line) <= 42 for line in lines)


def test_slot_ticket_prints_through_the_scheduler(settings):
    with TestClient(create_app(settings)) as client:
        app = client.app
        ticket = client.post("/api/v1/tickets/slots", json={"template": 102, "recipient": "wife", "slots": {"paragraph": "Hi"}}).json()
        assert app.state.scheduler.run_once() == 1
        assert client.get(f"/api/v1/tickets/{ticket['id']}").json()["status"] == "sent"


def test_legacy_templates_endpoint_still_lists_only_printed_layouts(settings):
    with TestClient(create_app(settings)) as client:
        ids = [t["id"] for t in client.get("/api/v1/templates").json()]
        assert ids == list(range(1, 13))


def test_slot_ticket_can_be_held_and_keyed(settings):
    with TestClient(create_app(settings)) as client:
        body = {"template": 101, "recipient": "yannic", "hold": True, "hold_key": "user-home",
                "idempotency_key": "morning:yannic:2026-10-26"}
        first = client.post("/api/v1/tickets/slots", json=body).json()
        again = client.post("/api/v1/tickets/slots", json=body).json()
        assert first["status"] == "held" and first["hold_key"] == "user-home"
        assert again["id"] == first["id"]


def test_slot_hold_rules_match_plain_tickets(settings):
    with TestClient(create_app(settings)) as client:
        both = client.post(
            "/api/v1/tickets/slots",
            json={"template": 102, "recipient": "wife", "slots": {"paragraph": "x"}, "hold": True,
                  "send_at": "2026-10-26T07:00:00"},
        )
        assert both.status_code == 422
        key_only = client.post(
            "/api/v1/tickets/slots", json={"template": 102, "recipient": "wife", "slots": {"paragraph": "x"}, "hold_key": "k"}
        )
        assert key_only.status_code == 422


def test_slot_blocks_need_home_assistant(settings):
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/v1/tickets/slots",
            json={"template": 102, "recipient": "wife", "slots": {"paragraph": "x"},
                  "blocks": [{"type": "value", "entity_id": "sensor.a", "label": "A"}]},
        )
        assert response.status_code == 422  # Home Assistant is not configured in the test settings
        assert "Home Assistant" in response.json()["detail"]
