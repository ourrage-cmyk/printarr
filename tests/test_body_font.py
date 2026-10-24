"""Body text is full-line (Inter). The dot matrix font is for titles only.

The renderers draw text through Canvas.text (dot matrix) or Canvas.solid (full-line). These tests
record every dot-matrix draw and the function that made it, so a body line drawn in the dot font
fails here, whichever block or design it is in.
"""

import sys

import pytest

from app.render import canvas, designs, strips
from app.render.strips import Block

# Functions allowed to draw in the dot matrix font: titles, headings and pill labels only.
TITLE_CALLERS = {"_heading", "_greeting", "_title_line", "title"}

BLOCKS = {
    "greeting": {"greeting": "Good morning, Yannic", "summary": "Cloudy, 12 C. Bins out tonight."},
    "metric": {"label": "Body battery", "value": 74, "unit": "%", "series": [40, 52, 61, 74]},
    "metric_rows": {"title": "Home now", "rows": [{"label": "Power", "value": 0.42, "unit": "kWh"}]},
    "graph": {"title": "Living room", "series": [18, 19, 21, 21.5], "unit": "C"},
    "dog_counts": {"dogs": [{"name": "Milo", "pee": 3, "poop": 1, "food": 2, "run": 1}]},
    "message": {"title": "Parcel", "paragraph": "Parcel is at the back door. Bring it in before the rain.", "from": "Yannic"},
    "alert": {"label": "WATER LEAK", "paragraph": "Kitchen sensor is wet. Check under the sink.", "action": "Turn off the tap"},
    "checklist": {"title": "Shopping", "items": [{"text": "Milk", "checked": False}, {"text": "Bread", "checked": True}]},
    "tip": {"tip": "Leave ten minutes early when it rains."},
    "fact": {"paragraph": "A dot matrix head prints one row at a time."},
}


@pytest.fixture
def dot_draws(monkeypatch):
    """Records (function that drew it, text) for every Canvas.text call while the test runs."""
    draws: list[tuple[str, str, int]] = []
    original = canvas.Canvas.text

    def recording(self, x, y, text, scale=2):
        draws.append((sys._getframe(1).f_code.co_name, str(text), scale))
        return original(self, x, y, text, scale)

    monkeypatch.setattr(canvas.Canvas, "text", recording)
    return draws


def _assert_titles_only(draws: list[tuple[str, str]]) -> None:
    body = [(caller, text) for caller, text, _ in draws if caller not in TITLE_CALLERS]
    assert not body, f"body text drawn in the dot matrix font: {body}"


@pytest.mark.parametrize("name", sorted(BLOCKS))
def test_block_body_text_is_full_line(name, dot_draws):
    strips.render_strip([Block(name, BLOCKS[name])])
    _assert_titles_only(dot_draws)


@pytest.mark.parametrize("mood", sorted(strips.MOODS))
def test_message_in_every_mood_is_full_line(mood, dot_draws):
    strips.render_strip([Block("message", BLOCKS["alert"], mood=mood)])
    _assert_titles_only(dot_draws)


def test_morning_design_body_text_is_full_line(dot_draws):
    designs.morning_system(
        designs.Morning(summary="Cloudy, 12 C. Bridget has been out twice.", body_battery=74, stress=21, steps=6120, cpu=18, ram=63)
    )
    _assert_titles_only(dot_draws)
    # The title words are still dot matrix: the design is a titled card, not all body text.
    assert {text for caller, text, _ in dot_draws if caller == "title"} == {"HELLO YANNIC", "TODAY"}


def test_morning_design_with_no_data_is_full_line(dot_draws):
    designs.morning_system(designs.Morning(summary="Good morning.", body_battery=None, stress=None, steps=None, cpu=None, ram=None))
    _assert_titles_only(dot_draws)


def test_every_title_is_larger_than_body_text(dot_draws):
    """Dot-matrix titles must be bigger than body text: at equal size the dot font reads grey and weaker."""
    strips.render_strip([Block("message", BLOCKS["alert"], mood="urgent")])
    strips.render_strip([Block("graph", BLOCKS["graph"])])
    strips.render_strip([Block("checklist", BLOCKS["checklist"])])
    strips.render_strip([Block("greeting", BLOCKS["greeting"])])
    titles = [scale for caller, _, scale in dot_draws if caller in TITLE_CALLERS]
    assert titles, "expected dot-matrix titles to be drawn"
    assert all(scale > strips.BODY for scale in titles), titles
