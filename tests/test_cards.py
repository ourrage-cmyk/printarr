"""Briefings and notes draw as cards in the shared shell, with Home Assistant history as sparklines."""

from app import compose
from app.compose import briefing_blocks, message_blocks, ticket_lines
from app.ha import HAError


class FakeHA:
    def __init__(self, history: dict[str, list[float]], states: dict[str, str] | None = None) -> None:
        self.history = history
        self.states = states or {}

    def state(self, entity: str) -> str:
        if entity not in self.states:
            raise HAError(f"no entity {entity}")
        return self.states[entity]

    def numeric_history(self, entity: str, hours: int) -> list[float]:
        if entity not in self.history:
            raise HAError(f"no history for {entity}")
        return self.history[entity]


BRIEFING = {
    "greeting": "Good morning, Yannic",
    "paragraph": "Cloudy, 12 C. Bridget has been out twice.",
    "metrics": [
        {"label": "Body battery", "entity_id": "sensor.body_battery", "unit": "%"},
        {"label": "Steps", "value": 6120},
        {"label": "Energy", "series": [0.07, 0.08, 0.079]},
    ],
    "tip": "Leave five minutes early.",
}


def test_entity_metric_gets_a_sparkline_from_history():
    client = FakeHA({"sensor.body_battery": [60.0, 65.0, 72.0]}, {"sensor.body_battery": "72"})
    blocks = briefing_blocks(BRIEFING, client)
    body_battery = next(b for b in blocks if b["slots"].get("label") == "Body battery")
    assert body_battery["slots"]["series"] == [60.0, 65.0, 72.0]
    assert body_battery["slots"]["entity_id"] == "sensor.body_battery"


def test_briefing_falls_back_to_a_text_value_without_history():
    client = FakeHA({}, {"sensor.body_battery": "72"})
    blocks = briefing_blocks(BRIEFING, client)
    body_battery = next(b for b in blocks if b["slots"].get("label") == "Body battery")
    assert "series" not in body_battery["slots"]
    lines, notes = compose.compose_render(blocks, client)
    assert len(lines) == 1 and lines[0].raster is not None


def test_briefing_is_drawn_as_one_card_strip():
    lines = ticket_lines(BRIEFING, None, template_id=101)
    assert len(lines) == 1
    assert lines[0].raster is not None


def test_long_history_is_thinned_to_the_sparkline_points():
    values = [float(i) for i in range(400)]
    series = compose._history("sensor.x", 24, FakeHA({"sensor.x": values}))
    assert series is not None and len(series) <= compose.HISTORY_POINTS
    assert series[0] == 0.0 and series[-1] >= 390.0


def test_a_note_is_a_message_card_signed_by_its_sender():
    blocks = message_blocks("Bins are out.", "Allyson", title="Note")
    assert blocks[0]["type"] == "message"
    assert blocks[0]["slots"]["from"] == "Allyson"
    lines = ticket_lines({"paragraph": "Bins are out."}, None, template_id=102, sender="Allyson")
    assert len(lines) == 1 and lines[0].raster is not None


def test_a_note_without_a_sender_is_signed_by_printarr():
    assert message_blocks("Hi", None)[0]["slots"]["from"] == "Printarr"
