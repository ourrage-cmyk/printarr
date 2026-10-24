import json

import pytest
from fastapi.testclient import TestClient

from app import compose
from app.compose import BlockProblem, catalogue, compose_render, fill_values, validate_blocks
from app.main import create_app
from app.render import strips
from app.store import TicketStore


LONG_TEXT = "Lorem ipsum dolor sit amet consectetur " * 20  # too much for a 2-column message card


class FakeHA:
    def __init__(self, states: dict[str, str]) -> None:
        self.states = states

    def state(self, entity: str) -> str:
        from app.ha import HAError

        if entity not in self.states:
            raise HAError(f"no entity {entity}")
        return self.states[entity]


def test_block_types_match_the_renderer():
    assert set(compose.BLOCKS) == set(strips.LAYOUT)
    assert {b["type"] for b in catalogue()} == set(strips.LAYOUT)


def test_catalogue_and_schema_list_span(settings):
    with TestClient(create_app(settings)) as client:
        types = {b["type"] for b in client.get("/api/v1/blocks").json()}
        assert {"greeting", "metric", "graph", "message", "checklist", "alert"} <= types
        schema = client.get("/api/v1/blocks/alert/schema").json()
        assert schema["span"]["default"] == 3 and schema["span"]["min"] == 2
        assert schema["properties"]["label"]["maxLength"] == 40
        assert client.get("/api/v1/blocks/nope/schema").status_code == 404


def test_composed_ticket_stores_blocks_and_moods(settings):
    body = {
        "recipient": "yannic",
        "blocks": [
            {"type": "greeting", "mood": "happy", "slots": {"greeting": "Good morning, Yannic"}},
            {"type": "metric", "mood": "factual", "slots": {"label": "steps", "value": 6120}},
            {"type": "tip", "mood": "reminder", "slots": {"tip": "Leave early."}},
        ],
    }
    with TestClient(create_app(settings)) as client:
        ticket = client.post("/api/v1/tickets/compose", json=body).json()
    assert ticket["template_id"] == 103
    assert ticket["notes"] == []
    assert TicketStore(settings.db_path).get(ticket["id"])["moods"] == "happy,factual,reminder"
    stored = json.loads(TicketStore(settings.db_path).get(ticket["id"])["slots_json"])
    assert [b["type"] for b in stored["blocks"]] == ["greeting", "metric", "tip"]
    assert [b["span"] for b in stored["blocks"]] == [3, 1, 3]


def test_bad_blocks_return_422_with_their_position(settings):
    body = {"recipient": "wife", "blocks": [
        {"type": "greeting", "mood": "happy", "slots": {"greeting": "Hi"}},
        {"type": "tip", "mood": "smug", "slots": {"tip": "x"}},
        {"type": "alert", "mood": "urgent", "slots": {"label": "x", "paragraph": "y", "colour": "red"}},
    ]}
    with TestClient(create_app(settings)) as client:
        response = client.post("/api/v1/tickets/compose", json=body)
    assert response.status_code == 422
    slots = [p["slot"] for p in response.json()["detail"]]
    assert "blocks[1].mood" in slots and "blocks[2].slots.colour" in slots


def test_span_is_checked_against_the_block_minimum():
    with pytest.raises(BlockProblem) as exc:
        validate_blocks([{"type": "alert", "mood": "urgent", "span": 1,
                          "slots": {"label": "LEAK", "paragraph": "Under the sink."}}])
    assert exc.value.problems[0]["slot"] == "blocks[0].span"
    with pytest.raises(BlockProblem):
        validate_blocks([{"type": "tip", "mood": "neutral", "span": 4, "slots": {"tip": "x"}}])


def test_auto_mood_resolves_to_neutral_until_the_model_picks():
    checked = validate_blocks([{"type": "fact", "mood": "auto", "slots": {"paragraph": "Octopuses have three hearts."}}])
    assert checked[0]["mood"] == "neutral"
    assert checked[0]["span"] == 3


def test_metric_needs_a_value_or_an_entity():
    with pytest.raises(BlockProblem):
        validate_blocks([{"type": "metric", "mood": "factual", "slots": {"label": "steps"}}])


def test_checklist_and_dog_rows_are_checked():
    with pytest.raises(BlockProblem):
        validate_blocks([{"type": "dog_counts", "mood": "happy", "slots": {"dogs": [{"pee": 1}]}}])
    with pytest.raises(BlockProblem):
        validate_blocks([{"type": "checklist", "mood": "neutral", "slots": {"items": [{"checked": True}]}}])


def test_composed_ticket_renders_raster_strips_with_no_text_layout():
    checked = validate_blocks([
        {"type": "greeting", "mood": "happy", "slots": {"greeting": "Hello"}},
        {"type": "checklist", "mood": "neutral", "slots": {"items": [{"text": "Bins", "checked": True}]}},
    ])
    lines, notes = compose_render(checked, None)
    assert len(lines) == 1 and notes == []
    width_bytes, height, data = lines[0].raster
    assert width_bytes == 64 and len(data) == width_bytes * height


def test_a_greeting_starts_a_new_strip():
    checked = validate_blocks([
        {"type": "tip", "mood": "neutral", "slots": {"tip": "One"}},
        {"type": "greeting", "mood": "happy", "slots": {"greeting": "Hi"}},
    ])
    lines, _ = compose_render(checked, None)
    assert len(lines) == 2


def test_long_text_is_shortened_and_reported():
    checked = validate_blocks([{"type": "message", "mood": "neutral", "span": 2, "slots": {
        "paragraph": LONG_TEXT, "from": "Yannic"}}])
    _, notes = compose_render(checked, None)
    assert any(note.startswith("message shortened") for note in notes)


def test_entity_values_are_filled_before_drawing():
    checked = validate_blocks([{"type": "metric_rows", "mood": "factual", "slots": {"rows": [
        {"label": "Battery", "entity_id": "sensor.battery"},
        {"label": "Steps", "value": 6120},
    ]}}])
    client = FakeHA({"sensor.battery": "72"})
    filled = fill_values(checked, compose.fetch_entities(checked, client))
    assert filled[0]["slots"]["rows"][0]["value"] == "72"
    assert filled[0]["slots"]["rows"][1]["value"] == 6120
    lines, _ = compose_render(checked, client)
    assert len(lines) == 1


def test_missing_entity_prints_a_placeholder():
    checked = validate_blocks([{"type": "metric", "mood": "factual", "slots": {
        "label": "Steps", "entity_id": "sensor.steps"}}])
    filled = fill_values(checked, compose.fetch_entities(checked, FakeHA({})))
    assert filled[0]["slots"]["value"] == compose.PLACEHOLDER


def test_composed_ticket_response_has_notes(settings):
    body = {"recipient": "yannic", "blocks": [
        {"type": "message", "mood": "neutral", "span": 2, "slots": {"paragraph": LONG_TEXT, "from": "Allyson"}}]}
    with TestClient(create_app(settings)) as client:
        ticket = client.post("/api/v1/tickets/compose", json=body).json()
    assert any(note.startswith("message shortened") for note in ticket["notes"])
