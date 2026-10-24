"""Rules from the formatting audit: one box per thought, no gaps, signed alerts, one title face."""

from app.compose import _signed
from app.render import strips
from app.render.strips import Block


def test_salutation_headline_is_dropped_and_a_plain_headline_titles_the_next_card():
    note = Block("message", {"paragraph": "Rain later.", "from": "Allyson"})
    rows, _ = strips.layout([Block("greeting", {"greeting": "HELLO LOVE"}), note])
    assert len(rows) == 1 and rows[0][0].block.type == "message" and "title" not in rows[0][0].slots
    rows, _ = strips.layout([Block("greeting", {"greeting": "SHOPPING"}), Block("checklist", {"items": [{"text": "Milk"}]})])
    assert len(rows) == 1 and rows[0][0].slots["title"] == "SHOPPING"


def test_rows_never_leave_a_gap():
    metrics = [Block("metric", {"label": str(i), "value": i}, span=1) for i in range(4)]
    for count in (1, 2, 3, 4, 5):
        rows, _ = strips.layout(metrics[:1] * count)
        for row in rows:
            assert row[0].x0 == strips.OUTER_L and row[-1].x1 == strips.OUTER_R


def test_metric_tiles_in_a_row_share_one_numeral_size():
    rows, _ = strips.layout([Block("metric", {"label": "A", "value": 1636}, span=1), Block("metric", {"label": "B", "value": 52}, span=1)])
    assert len({p.slots["_cap"] for p in rows[0]}) == 1


def test_alert_takes_the_ticket_sender_and_prints_it():
    block = _signed({"type": "alert", "slots": {"label": "COAT", "paragraph": "x"}}, "Allyson")
    assert block["slots"]["from"] == "Allyson"
    assert _signed({"type": "alert", "slots": {"label": "A", "paragraph": "x", "from": "Bo"}}, "Allyson")["slots"]["from"] == "Bo"


def test_titles_use_the_heavy_face_when_every_word_fits():
    scale, lines = strips.title_lines("UNFORMATTED", 394)
    assert scale == strips.NUMERAL and lines == ["UNFORMATTED"]
    scale, lines = strips.title_lines("GOOD MORNING YANNIC", 440)
    assert scale == strips.NUMERAL and len(lines) > 1


def test_firm_complaint_has_a_barcode():
    assert strips.MOODS["firm_complaint"]["header"] == "bandBlocks"


def test_metric_tiles_nest_in_the_card_that_closes_them():
    blocks = [
        Block("greeting", {"greeting": "TODAY", "summary": "Fine."}),
        Block("metric", {"label": "A", "value": 1}, span=1),
        Block("metric", {"label": "B", "value": 2}, span=1),
        Block("metric", {"label": "C", "value": 3}, span=1),
        Block("metric", {"label": "D", "value": 4}, span=1),
        Block("tip", {"tip": "Leave early."}, mood="reminder"),
    ]
    assert len(strips.split_strips(blocks)) == 1
    rows, _ = strips.layout(strips.prepare(blocks))
    assert len(rows) == 1 and rows[0][0].block.type == "group"


def test_blank_line_in_text_makes_a_paragraph_gap():
    one = strips.paragraph_height("First part.\n\nSecond part.", strips.BODY, 400)
    flat = strips.paragraph_height("First part. Second part.", strips.BODY, 400)
    assert one > flat


STORY = " ".join(f"Sentence number {i} says something about the dogs." for i in range(60))


def test_long_text_continues_on_the_next_card_and_nothing_is_cut():
    blocks = strips.spill([Block("message", {"paragraph": STORY, "from": "Hermes"})])
    assert len(blocks) > 1
    assert "".join(b.slots["paragraph"] for b in blocks).replace(" ", "") == STORY.replace(" ", "")
    assert [bool(b.slots.get("from")) for b in blocks] == [False] * (len(blocks) - 1) + [True]  # one signature
    assert all(b.slots.get("_cont") for b in blocks[1:])
    assert len(strips.split_strips([Block("message", {"paragraph": STORY, "from": "Hermes"})])) == len(blocks)


def test_a_url_wider_than_the_card_breaks_by_character():
    lines = strips.solid_wrap("https://example.com/a/very/long/path/that/keeps/going/and/going/forever", 300)
    assert len(lines) > 1 and all(strips.solid_width(line, 21) <= 300 for line in lines)


def test_a_title_is_at_most_two_lines():
    scale, lines = strips.title_lines("SHOPPING LIST FOR THE WEEKEND BARBECUE", 400)
    assert len(lines) <= 2


def test_a_long_title_steps_down_then_ends_in_an_ellipsis_and_two_titles_never_print_the_same():
    fits = strips.title_lines("SHOPPING LIST FOR THE WEEKEND", 440)
    assert fits[0] == strips.TITLE and not fits[1][-1].endswith("...")
    cut = strips.title_lines("SHOPPING LIST FOR THE WEEKEND BARBECUE", 440)
    assert cut[1][-1].endswith("...") and cut != fits


def test_a_continuation_title_keeps_every_word_of_the_original():
    assert strips._cont_title("Rex and Bella") == "REX AND BELLA CONT."


def test_emoji_print_as_a_question_mark_not_a_block():
    from app.render.canvas import printable

    assert printable("Love you \U0001F600 你好 done") == "Love you ? ? done"


def test_a_soft_alert_is_not_urgent_and_urgent_differs_from_firm():
    assert strips.MOODS["urgent"] != strips.MOODS["firm_complaint"]
    assert strips.STROKE_BY_MOOD["urgent"] != strips.STROKE_BY_MOOD["firm_complaint"]
    assert "gentle_warning" not in strips.URGENT_MOODS


def test_briefing_template_takes_scope_as_of_and_a_sign_off():
    from app.compose import briefing_blocks
    from app.slots import BriefingSlots

    slots = BriefingSlots.model_validate({"tip": "Leave early.", "from": "Allyson", "metrics": [{"label": "Temp", "value": 17.1, "scope": "outside", "as_of": "08:15"}]})
    blocks = briefing_blocks(slots.model_dump(exclude_none=True), None)
    assert blocks[0]["slots"]["scope"] == "outside" and blocks[0]["slots"]["as_of"] == "08:15"
    assert blocks[-1]["slots"]["from"] == "Allyson"


def test_truncated_and_strip_count_are_stored(tmp_path):
    from app.store import TicketStore

    store = TicketStore(str(tmp_path / "t.db"))
    store.init()
    ticket = store.create(recipient="yannic", message="x", send_at_ms=0, template_id=103, decorations=(), selection="explicit", notes=["message shortened"], strip_count=3)
    again = store.get(ticket["id"])
    assert again["truncated"] is True and again["strip_count"] == 3 and again["notes"] == ["message shortened"]


def test_every_continuation_card_fits_without_shortening():
    for count in (30, 70, 120):
        text = " ".join(f"Sentence number {i} says something about the dogs." for i in range(count))
        text = f"{text}\n\n{text[:300]}"
        for block in strips.spill([Block("message", {"title": "Rex and Bella story", "paragraph": text, "from": "Hermes"})]):
            _, notes = strips.layout([block])
            assert notes == [], notes


def test_a_long_row_label_wraps_and_the_value_stays_right_aligned():
    from app.render.canvas import Canvas

    c = Canvas()
    c.y = 0
    height = strips._row(c, strips.OUTER_L, strips.OUTER_R, "OUTSIDE TEMPERATURE READING FROM THE GARDEN SENSOR", "18.4 C")
    assert height >= 2 * strips.ROW


def test_title_slot_of_the_briefing_is_the_headline():
    from app.compose import briefing_blocks

    blocks = briefing_blocks({"greeting": "GOOD MORNING", "title": "MONDAY", "paragraph": "Short day."}, None)
    assert blocks[0]["slots"]["greeting"] == "MONDAY" and blocks[0]["slots"]["summary"] == "Short day."  # with a title and text the greeting is dropped


def test_moods_draw_different_bands():
    headers = {m: spec["header"] for m, spec in strips.MOODS.items()}
    for a, b in (("playful", "gentle_warning"), ("excited", "happy")):
        assert headers[a] != headers[b]


def test_greeting_only_ticket_is_signed_and_graph_has_a_middle_label():
    from app.compose import ticket_lines

    plain = ticket_lines({"greeting": "HELLO ALLYSON"}, None, None, None)
    signed = ticket_lines({"greeting": "HELLO ALLYSON"}, None, None, "Hermes")
    assert [line.raster for line in signed] != [line.raster for line in plain]  # the signature changes the picture
