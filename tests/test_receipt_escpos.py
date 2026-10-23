from datetime import datetime
from zoneinfo import ZoneInfo

from app.escpos import INITIALIZE, PARTIAL_CUT, encode, to_text
from app.receipt import Line, Receipt, render_lines, wrap

SENT = datetime(2026, 10, 23, 21, 30, tzinfo=ZoneInfo("Europe/London"))


def test_wrap_respects_width():
    rows = wrap("word " * 30, 48)
    assert len(rows) > 1
    assert all(len(row) <= 48 for row in rows)


def test_wrap_breaks_long_words():
    assert [len(row) for row in wrap("x" * 100, 48)] == [48, 48, 4]


def test_wrap_keeps_line_breaks():
    assert wrap("a\n\nb", 48) == ["a", "", "b"]


def test_render_places_title_and_names():
    receipt = Receipt(
        recipient="Anna", sender="Yannic", title="Dinner", message="Pasta at 7", sent_at=SENT
    )
    lines = render_lines(receipt, 48)
    texts = [line.text for line in lines]
    assert "TO: Anna" in texts
    assert "FROM: Yannic" in texts
    title = next(line for line in lines if line.text == "Dinner")
    assert title.tall and title.bold and title.align == "center"


def test_encode_frames_the_job():
    receipt = Receipt(recipient="Anna", message="Pasta at 7", sent_at=SENT)
    payload = encode(render_lines(receipt, 48))
    assert payload.startswith(INITIALIZE)
    assert payload.endswith(PARTIAL_CUT)
    assert b"Pasta at 7" in payload


def test_encode_replaces_unsupported_characters():
    payload = encode([Line("café 😀")])
    assert b"caf\x82 ?\n" in payload  # é is in cp437, the emoji is not


def test_text_preview_fits_paper_width():
    receipt = Receipt(recipient="Anna", message="Hello " * 40, sent_at=SENT, title="Hi")
    text = to_text(render_lines(receipt, 48), 48)
    assert all(len(line) <= 48 for line in text.splitlines())
    assert "21:30" in text
