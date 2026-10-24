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
    assert strips.MOODS["firm_complaint"]["header"] == "barcode"
