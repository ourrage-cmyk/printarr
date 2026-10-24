from fastapi.testclient import TestClient

from app.compose import compose_lines, validate_blocks, BlockProblem
from app.main import create_app
from app.store import TicketStore


def test_catalogue_and_schema_are_listed(settings):
    with TestClient(create_app(settings)) as client:
        types = {b["type"] for b in client.get("/api/v1/blocks").json()}
        assert {"greeting", "metric_tiles", "graph", "message", "list", "todo", "alert"} <= types
        assert client.get("/api/v1/blocks/tip/schema").json()["properties"]["text"]["maxLength"] == 120
        assert client.get("/api/v1/blocks/nope/schema").status_code == 404


def test_composed_ticket_stores_blocks_and_moods(settings):
    import json

    body = {
        "recipient": "yannic",
        "blocks": [
            {"type": "greeting", "mood": "happy", "slots": {"text": "Good morning, Yannic"}},
            {"type": "metric_tiles", "mood": "factual", "slots": {"metrics": [{"label": "steps", "value": 6120}]}},
            {"type": "tip", "mood": "reminder", "slots": {"text": "Leave early."}},
        ],
    }
    with TestClient(create_app(settings)) as client:
        ticket = client.post("/api/v1/tickets/compose", json=body).json()
    assert ticket["template_id"] == 103
    assert TicketStore(settings.db_path).get(ticket["id"])["moods"] == "happy,factual,reminder"
    stored = json.loads(TicketStore(settings.db_path).get(ticket["id"])["slots_json"])
    assert [b["type"] for b in stored["blocks"]] == ["greeting", "metric_tiles", "tip"]


def test_bad_blocks_return_422_with_their_position(settings):
    body = {"recipient": "wife", "blocks": [
        {"type": "greeting", "mood": "happy", "slots": {"text": "Hi"}},
        {"type": "tip", "mood": "smug", "slots": {"text": "x"}},
        {"type": "alert", "mood": "urgent", "slots": {"text": "x", "colour": "red"}},
    ]}
    with TestClient(create_app(settings)) as client:
        response = client.post("/api/v1/tickets/compose", json=body)
    assert response.status_code == 422
    slots = [p["slot"] for p in response.json()["detail"]]
    assert "blocks[1].mood" in slots and "blocks[2].slots.colour" in slots


def test_auto_mood_resolves_to_neutral_until_the_model_picks():
    checked = validate_blocks([{"type": "paragraph", "mood": "auto", "slots": {"text": "Hi"}}])
    assert checked[0]["mood"] == "neutral"


def test_metric_tiles_limit_is_two():
    import pytest

    with pytest.raises(BlockProblem):
        validate_blocks([{"type": "metric_tiles", "mood": "factual", "slots": {"metrics": [
            {"label": "a", "value": 1}, {"label": "b", "value": 2}, {"label": "c", "value": 3}]}}])


def test_compose_text_layout_stacks_blocks_in_order():
    checked = validate_blocks([
        {"type": "greeting", "mood": "happy", "slots": {"text": "Hello"}},
        {"type": "todo", "mood": "neutral", "slots": {"items": [{"text": "Bins", "done": True}]}},
    ])
    texts = [line.text for line in compose_lines(checked)]
    assert texts == ["Hello", "[x] Bins"]
