"""No line of text runs into the card border: every full-line draw keeps EDGE_GAP to the right edge."""

import pytest

from app.render import canvas, strips
from app.render.canvas import Canvas, solid_width
from app.render.strips import Block

CASES = {
    "dog_counts_long": Block("dog_counts", {"dogs": [
        {"name": "Pip", "pee": 3, "poop": 1, "food": 2, "run": 1},
        {"name": "Oscar", "pee": 12, "poop": 10, "food": 2, "run": 0},
    ]}),
    "alert_action": Block("alert", {"label": "DOOR", "paragraph": "Front door is open.", "action": "Open the door"}, mood="urgent"),
    "checklist_long": Block("checklist", {"title": "Shopping", "items": [{"text": "Phone charger", "checked": False}]}),
    "metric_steps": Block("metric", {"label": "Steps", "value": 9412, "unit": "steps"}),
    "metric_rows": Block("metric_rows", {"title": "Home", "rows": [{"label": "Humidity", "value": 54, "unit": "%"}]}),
}


@pytest.fixture
def solid_draws(monkeypatch):
    draws: list[tuple[int, str, int]] = []
    original = Canvas.solid

    def recording(self, x, y, text, cap=21):
        draws.append((x, str(text), cap))
        return original(self, x, y, text, cap)

    monkeypatch.setattr(Canvas, "solid", recording)
    return draws


@pytest.mark.parametrize("name", sorted(CASES))
def test_full_line_text_keeps_the_edge_gap(name, solid_draws):
    strips.render_strip([CASES[name]])
    limit = strips.OUTER_R - strips.EDGE_GAP
    for x, text, cap in solid_draws:
        right = x + solid_width(text, cap)
        assert right <= limit, f"{text!r} ends at {right}, past the limit {limit}"


def test_row_drops_the_value_under_the_label_when_it_cannot_fit(solid_draws):
    c = Canvas()
    c.y = 0
    height = strips._row(c, strips.OUTER_L, strips.OUTER_R, "A VERY LONG LABEL FOR A ROW", "99999 STEPS PER DAY ALL DAY LONG", indent=0)
    assert height >= 2 * strips.ROW  # the value is under the label, wrapped if it is wider than the line
