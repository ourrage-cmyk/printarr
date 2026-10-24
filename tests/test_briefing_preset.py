"""The briefing preset: one fixed layout for Hermes' briefing, sent as preset instead of blocks."""

import pytest
from fastapi.testclient import TestClient

from app.compose import BlockProblem, briefing_preset_blocks
from app.main import create_app

SLOTS = {
    "time_of_day": "morning",
    "metrics": [
        {"label": "Steps", "value": 4200},
        {"label": "Inside", "value": 21.5, "unit": "C"},
        {"label": "Battery", "value": 88, "unit": "%"},
    ],
    "graph": {"title": "Heart rate", "series": [60, 64, 70, 66, 62]},
    "body": "Two dogs walked before breakfast. Rain after lunch.",
    "fun_fact": "Octopuses have three hearts.",
    "from": "Hermes",
}


def types_of(blocks):
    return [b["type"] for b in blocks]


def test_preset_lays_out_time_metrics_graph_body_and_fact_in_order():
    blocks = briefing_preset_blocks(SLOTS, None, "Yannic")
    assert types_of(blocks) == ["greeting", "metric", "metric", "metric", "graph", "message", "fact"]
    assert blocks[0]["slots"] == {"greeting": "GOOD MORNING"}
    assert blocks[5]["slots"]["from"] == "Hermes"
    assert blocks[6]["mood"] == "playful"


def test_an_entity_graph_without_history_is_left_out_and_the_rest_prints():
    slots = {**SLOTS, "graph": {"title": "Heart rate", "entity_id": "sensor.heart_rate"}}
    assert "graph" not in types_of(briefing_preset_blocks(slots, None, "Yannic"))


def test_the_sender_signs_the_body_when_no_sign_off_is_sent():
    slots = {k: v for k, v in SLOTS.items() if k != "from"}
    blocks = briefing_preset_blocks(slots, None, "Yannic")
    assert blocks[5]["slots"]["from"] == "Yannic"


@pytest.mark.parametrize("bad", [
    {"time_of_day": "midnight"},
    {"metrics": SLOTS["metrics"][:2]},
    {"graph": {"title": "Heart rate"}},
])
def test_wrong_preset_slots_name_the_slot(bad):
    with pytest.raises(BlockProblem) as caught:
        briefing_preset_blocks({**SLOTS, **bad}, None, "Yannic")
    assert caught.value.problems and caught.value.problems[0]["slot"].startswith("preset.slots")


def test_the_endpoint_takes_a_preset_and_rejects_preset_with_blocks(settings):
    with TestClient(create_app(settings)) as client:
        ok = client.post("/api/v1/tickets/compose", json={"recipient": "yannic", "preset": "briefing", "slots": SLOTS})
        assert ok.status_code == 201, ok.text
        assert ok.json()["kind"] == "morning"
        both = client.post("/api/v1/tickets/compose", json={
            "recipient": "yannic", "preset": "briefing", "slots": SLOTS,
            "blocks": [{"type": "tip", "mood": "neutral", "slots": {"tip": "x"}}],
        })
        assert both.status_code == 422
        bad = client.post("/api/v1/tickets/compose", json={"recipient": "yannic", "preset": "briefing", "slots": {**SLOTS, "time_of_day": "night"}})
        assert bad.status_code == 422 and "preset.slots.time_of_day" in bad.text
