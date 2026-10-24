"""Charts say what they show: the time span, the high and low, and NOW, with nothing past the tile edge."""

from app.render import strips
from app.render.strips import Block, Card, line_graph
from app.render.canvas import Canvas, solid_width

import pytest


def _graph_draws(monkeypatch, slots):
    texts = []
    original = Canvas.solid

    def recording(self, x, y, text, cap=21):
        texts.append(text)
        return original(self, x, y, text, cap)

    monkeypatch.setattr(Canvas, "solid", recording)
    strips.render_strip([Block("graph", slots)])
    return texts


def test_graph_shows_default_span_high_low_and_now(monkeypatch):
    texts = _graph_draws(monkeypatch, {"title": "Living room", "series": [18, 19, 21, 20.1], "unit": "C"})
    assert "24H" in texts
    assert "NOW" in texts
    assert "HIGH 21.0 C" in texts
    assert "LOW 18.0 C" in texts


def test_graph_uses_the_given_span(monkeypatch):
    texts = _graph_draws(monkeypatch, {"title": "Heat", "series": [1, 2, 3], "range": "12H"})
    assert "12H" in texts and "24H" not in texts


def test_metric_sparkline_has_a_span_label(monkeypatch):
    texts = []
    original = Canvas.solid

    def recording(self, x, y, text, cap=21):
        texts.append(text)
        return original(self, x, y, text, cap)

    monkeypatch.setattr(Canvas, "solid", recording)
    strips.render_strip([Block("metric", {"label": "Power", "value": 3, "unit": "kW", "series": [1, 2, 3], "range": "12H"})])
    assert "12H" in texts and "NOW" in texts


def test_long_tip_is_not_cut(monkeypatch):
    tip = "Leave ten minutes early when it rains, take the big umbrella, and check the bus times before you go out."
    rows, notes = strips.layout([Block("tip", {"tip": tip})])
    placed = rows[0][0]
    assert placed.slots["tip"] == tip
    assert not any("..." in str(note) for note in notes)


@pytest.mark.parametrize("span", ["24H", "12H"])
def test_axis_labels_fit_the_tile(span):
    width = solid_width(span, 14) + solid_width("NOW", 14)
    assert width < strips.OUTER_R - strips.OUTER_L


def test_no_card_content_runs_past_its_card():
    """A tile whose label wraps and has a sparkline still fits inside its card, so nothing overlaps the next card."""
    blocks = [
        Block("greeting", {"greeting": "Good morning, Yannic", "summary": "Cloudy, 12 C."}),
        Block("metric", {"label": "Body battery", "value": 74, "unit": "%", "series": [40, 52, 61, 58, 70, 74]}),
        Block("metric", {"label": "Stress", "value": 21, "series": [30, 28, 25, 22, 21]}),
        Block("metric", {"label": "Steps", "value": 6120, "series": [0, 1000, 3000, 6120]}),
        Block("tip", {"tip": "Leave ten minutes early when it rains."}),
    ]
    rows, _ = strips.layout(blocks)
    for row in rows:
        for placed in row:
            needed = placed.content_h + 2 * strips.PAD_V
            assert placed.units * strips.UNIT_H >= needed, (placed.block.type, placed.units, needed)
