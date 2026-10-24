import pytest

from app.render import strips
from app.render.canvas import ROW_BYTES
from app.render.strips import Block, MARGIN_BOTTOM, MARGIN_TOP, MOODS, RENDERERS, render_strip, split_strips


def greeting(name="Good morning, Yannic"):
    return Block("greeting", {"greeting": name, "summary": "Cloudy, 12 C."})


def tip(text="Leave early."):
    return Block("tip", {"tip": text})


def test_split_holds_at_most_five_blocks():
    blocks = [tip(str(i)) for i in range(7)]
    strips_out = split_strips(blocks)
    assert [len(s) for s in strips_out] == [5, 2]


def test_greeting_always_starts_a_new_strip():
    blocks = [tip("a"), tip("b"), greeting(), tip("c")]
    strips_out = split_strips(blocks)
    assert [[b.type for b in s] for s in strips_out] == [["tip", "tip"], ["greeting", "tip"]]


def test_strip_has_top_and_bottom_margins():
    bitmap = render_strip([tip()])
    assert bitmap.width == 512
    assert bitmap.height > MARGIN_TOP + MARGIN_BOTTOM
    # The first rows are blank: the top margin.
    first_rows = bitmap.bits[: ROW_BYTES * MARGIN_TOP]
    assert not any(first_rows)


def test_every_block_type_renders_in_every_mood():
    samples = {
        "greeting": {"greeting": "Good morning, Yannic", "summary": "Cloudy."},
        "metric_tiles": {"metrics": [{"label": "Body battery", "value": 72, "unit": "%"}, {"label": "Outside", "value": 12, "series": [8, 9, 12]}]},
        "metric_rows": {"title": "Energy", "rows": [{"label": "Now", "value": "0.079", "unit": "GBP/kWh"}]},
        "graph": {"title": "Outside", "series": [8.0, 9.0, 12.0], "unit": "C"},
        "dog_counts": {"dogs": [{"name": "Bridget", "pee": 3, "poop": 1, "food": 2, "run": 1}]},
        "message": {"title": "Note", "paragraph": "Thank you for the coffee.", "from": "Yannic"},
        "alert": {"label": "Water leak", "paragraph": "Turn off the stopcock.", "action": "Stopcock"},
        "checklist": {"title": "Shopping", "items": [{"text": "Milk"}, {"text": "Eggs", "checked": True}]},
        "tip": {"tip": "Check the bins."},
        "fact": {"paragraph": "Flamingos are pink from their food."},
    }
    for block_type, slots in samples.items():
        for mood in MOODS:
            bitmap = render_strip([Block(block_type, slots, mood)])
            assert bitmap.height > MARGIN_TOP + MARGIN_BOTTOM, (block_type, mood)


def test_one_ornament_per_card():
    card = strips.Card(strips.Canvas())
    card.c.y = 10
    first = card.ornament("loving", "header", 14, 498)
    second = card.ornament("loving", "divider", 14, 498)
    assert first > 0
    assert second == 0


def test_unknown_block_type_and_mood_are_refused():
    with pytest.raises(ValueError):
        render_strip([Block("video", {})])
    with pytest.raises(ValueError):
        render_strip([Block("tip", {"tip": "x"}, mood="sparkly")])


def test_a_strip_over_five_blocks_is_refused():
    with pytest.raises(ValueError):
        render_strip([tip(str(i)) for i in range(6)])


def test_renderers_cover_the_catalogue():
    from app.render.strips import BLOCKS

    assert set(RENDERERS) == set(BLOCKS)
