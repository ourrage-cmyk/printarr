"""Every printed strip shares one page: same width, side gutters and top and bottom margins.

These checks read the bitmap that the printer gets, so they catch drift in any block, mood or
card no matter which renderer drew it.
"""

import pytest

from app.render import strips
from app.render.canvas import PAPER_DOTS, ROW_BYTES, Bitmap
from app.render.strips import MARGIN_BOTTOM, MARGIN_TOP, OUTER_L, OUTER_R, Block

SAMPLES = {
    "greeting": {"greeting": "Good morning, Yannic", "summary": "Cloudy, 12 C."},
    "metric": {"label": "Body battery", "value": 74, "unit": "%", "series": [40, 52, 61, 74]},
    "metric_rows": {"title": "Home now", "rows": [{"label": "Power", "value": 0.42, "unit": "kWh"}]},
    "graph": {"title": "Living room", "series": [18, 19, 21, 21.5], "unit": "C"},
    "dog_counts": {"dogs": [{"name": "Milo", "pee": 3, "poop": 1, "food": 2, "run": 1}]},
    "message": {"title": "Parcel", "paragraph": "Parcel is at the back door.", "from": "Yannic"},
    "alert": {"label": "WATER LEAK", "paragraph": "Kitchen sensor is wet.", "action": "Turn off the tap"},
    "checklist": {"title": "Shopping", "items": [{"text": "Milk", "checked": False}]},
    "tip": {"tip": "Leave ten minutes early."},
    "fact": {"paragraph": "A dot matrix head prints one row at a time."},
}


def _ink_columns(bitmap: Bitmap) -> tuple[int, int]:
    """Leftmost and rightmost inked column over the whole bitmap."""
    left, right = PAPER_DOTS, -1
    for y in range(bitmap.height):
        row = bitmap.bits[y * ROW_BYTES : (y + 1) * ROW_BYTES]
        for x in range(PAPER_DOTS):
            if row[x >> 3] & (0x80 >> (x & 7)):
                left, right = min(left, x), max(right, x)
    return left, right


def _ink_rows(bitmap: Bitmap) -> tuple[int, int]:
    rows = [
        y
        for y in range(bitmap.height)
        if any(bitmap.bits[y * ROW_BYTES : (y + 1) * ROW_BYTES])
    ]
    return rows[0], rows[-1]


def _cases():
    for name, slots in SAMPLES.items():
        for mood in ("neutral", "happy"):
            yield pytest.param(Block(name, slots, mood=mood), id=f"{name}-{mood}")


@pytest.mark.parametrize("block", list(_cases()))
def test_strip_is_full_paper_width_with_shared_gutters(block):
    bitmap = strips.render_strip([block])
    assert bitmap.width == PAPER_DOTS
    left, right = _ink_columns(bitmap)
    assert left >= OUTER_L, f"ink at x={left}, inside the gutter"
    assert right <= OUTER_R, f"ink at x={right}, past the card edge"


@pytest.mark.parametrize("block", list(_cases()))
def test_strip_has_the_same_top_and_bottom_margins(block):
    bitmap = strips.render_strip([block])
    top, bottom = _ink_rows(bitmap)
    assert top == MARGIN_TOP
    assert bitmap.height - 1 - bottom >= MARGIN_BOTTOM - 1


def test_long_metric_unit_never_runs_past_the_tile():
    block = Block("metric", {"label": "Energy", "value": 1234.5, "unit": "GBP/KWH PEAK RATE"})
    _, right = _ink_columns(strips.render_strip([block]))
    assert right <= OUTER_R


def test_long_message_stays_inside_the_card():
    text = "word " * 200
    block = Block("message", {"paragraph": text.strip(), "from": "Yannic"})
    bitmap = strips.render_strip([block])
    left, right = _ink_columns(bitmap)
    assert left >= OUTER_L and right <= OUTER_R


@pytest.mark.parametrize("block", list(_cases()))
def test_no_wasted_paper_at_the_end_of_a_strip(block):
    """The blank under the last card is the shell's bottom margin, and nothing else."""
    bitmap = strips.render_strip([block])
    _, bottom = _ink_rows(bitmap)
    # The card's stroke ends one dot past its box, so the blank can differ from the margin by one dot.
    assert abs((bitmap.height - 1 - bottom) - MARGIN_BOTTOM) <= 1


FULL_WIDTH = ("greeting", "metric_rows", "graph", "dog_counts", "message", "alert", "checklist", "tip", "fact")


@pytest.mark.parametrize("name", FULL_WIDTH)
def test_full_width_cards_are_centred_with_equal_gutters(name):
    left, right = _ink_columns(strips.render_strip([Block(name, SAMPLES[name])]))
    assert left == OUTER_L
    assert PAPER_DOTS - 1 - right == PAPER_DOTS - OUTER_R - 1


def test_a_lone_metric_tile_takes_the_full_width():
    left, right = _ink_columns(strips.render_strip([Block("metric", SAMPLES["metric"])]))
    assert left == OUTER_L
    assert PAPER_DOTS - 1 - right == PAPER_DOTS - OUTER_R - 1
