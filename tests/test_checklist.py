"""A shopping list prints one item per line, each with its own box or tick."""

import pytest

from app.render import strips
from app.render.canvas import Canvas
from app.render.strips import Block


@pytest.fixture
def item_rows(monkeypatch):
    rows: list[tuple[int, str]] = []
    original = Canvas.solid

    def recording(self, x, y, text, cap=21):
        if text in {"MILK", "BREAD", "FLOWERS"}:
            rows.append((y, text))
        return original(self, x, y, text, cap)

    monkeypatch.setattr(Canvas, "solid", recording)
    return rows


def test_each_shopping_item_has_its_own_line(item_rows):
    items = [{"text": "Milk", "checked": False}, {"text": "Bread", "checked": True}, {"text": "Flowers", "checked": False}]
    strips.render_strip([Block("checklist", {"title": "Shopping", "items": items})])
    # The block is measured before it is drawn, so keep the last draw of each item.
    last = {text: y for y, text in item_rows}
    assert set(last) == {"MILK", "BREAD", "FLOWERS"}
    assert len(set(last.values())) == 3, f"items share a line: {last}"
