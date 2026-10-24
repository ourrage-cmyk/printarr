import pytest

from app.render import strips
from app.render.canvas import ROW_BYTES
from app.render.strips import Block, MARGIN_BOTTOM, MARGIN_TOP, MOODS, RENDERERS, render_strip, split_strips


def greeting(name="Good morning, Yannic"):
    return Block("greeting", {"greeting": name, "summary": "Cloudy, 12 C."})


def tip(text="Leave early."):
    return Block("tip", {"tip": text})


def test_split_cuts_by_height_not_by_count():
    assert len(split_strips([tip(str(i)) for i in range(7)])) == 1  # seven short tiles fit one strip
    blocks = [tip(str(i)) for i in range(40)]
    strips_out = split_strips(blocks)
    assert len(strips_out) > 1
    assert sum(len(b.slots.get("parts", [b])) for s in strips_out for b in s) == 40  # nothing is dropped


def test_greeting_always_starts_a_new_strip():
    blocks = [tip("a"), tip("b"), greeting(), tip("c")]
    strips_out = split_strips(blocks)
    assert len(strips_out) == 2 and [b.type for b in strips_out[0]] == ["tip", "tip"]
    assert [b.type for b in strips_out[1]] == ["greeting", "tip"]


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
        "metric": {"label": "Body battery", "value": 72, "unit": "%", "series": [8, 9, 12]},
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
    card = strips.Card(strips.Canvas(), "loving")
    card.c.y = 10
    before = card.c.y
    card.ornament("header", 14, 498)
    after_first = card.c.y
    card.ornament("divider", 14, 498)
    assert after_first > before
    assert card.c.y == after_first


def test_unknown_block_type_and_mood_are_refused():
    with pytest.raises(ValueError):
        render_strip([Block("video", {})])
    with pytest.raises(ValueError):
        render_strip([Block("tip", {"tip": "x"}, mood="sparkly")])


def test_a_strip_with_far_too_many_blocks_is_refused():
    with pytest.raises(ValueError):
        render_strip([tip(str(i)) for i in range(16)])


def test_renderers_cover_the_catalogue():
    from app.render.strips import BLOCKS

    assert set(RENDERERS) == set(BLOCKS)


def test_metric_tiles_pack_side_by_side():
    from app.render.strips import layout

    blocks = [Block("metric", {"label": "A", "value": 1}), Block("metric", {"label": "B", "value": 2}), Block("metric", {"label": "C", "value": 3})]
    rows, _ = layout(blocks)
    assert len(rows) == 1
    assert [p.col for p in rows[0]] == [0, 1, 2]


def test_one_and_two_column_row():
    from app.render.strips import layout

    blocks = [Block("metric", {"label": "A", "value": 1}), Block("alert", {"label": "HI", "paragraph": "Hi there."}, span=2)]
    rows, _ = layout(blocks)
    assert len(rows) == 1
    assert [p.span for p in rows[0]] == [1, 2]


def test_a_headline_needs_all_three_columns():
    with pytest.raises(ValueError):
        render_strip([Block("greeting", {"greeting": "Hi"}, span=1)])


def test_fluid_height_grows_with_text():
    from app.render.strips import layout

    short, _ = layout([Block("message", {"paragraph": "Hi."})])
    long, _ = layout([Block("message", {"paragraph": "A longer note for the day. " * 6})])
    assert long[0][0].units > short[0][0].units


def test_overflow_is_shortened_and_reported():
    from app.render.strips import LAYOUT, layout

    huge = Block("message", {"paragraph": "This is a very long message that keeps going. " * 60})
    rows, notes = layout([huge])
    placed = rows[0][0]
    assert placed.units <= LAYOUT["message"]["max_units"]
    assert placed.slots["paragraph"].endswith("...")
    assert notes


def test_rows_do_not_overlap_in_the_strip():
    bitmap = render_strip([greeting(), tip(), Block("metric", {"label": "A", "value": 1}), Block("metric", {"label": "B", "value": 2})])
    assert bitmap.height > MARGIN_TOP + MARGIN_BOTTOM
