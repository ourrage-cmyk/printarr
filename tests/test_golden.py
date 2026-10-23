"""Golden-byte tests: the exact ESC/POS stream for known jobs.

These pin our encoder's output so that any change to the bytes is deliberate. They
were generated from this encoder, not from Epson's Programming Guide, so they guard
against regressions. They do not prove the bytes match the printer. The simulator and
the real printer do that.

To regenerate after an intended change:  python -m tests.test_golden --regenerate
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.blocks import sparkline_bitmap
from app.escpos import (
    ALIGN,
    BOLD_OFF,
    BOLD_ON,
    CODE_PAGE_CP437,
    FEED_LINES,
    GS,
    INITIALIZE,
    LF,
    PARTIAL_CUT,
    TALL_OFF,
    TALL_ON,
    encode,
)
from app.receipt import Line, Receipt, render_lines

GOLDEN = Path(__file__).parent / "golden"
SENT = datetime(2026, 10, 24, 17, 30, tzinfo=ZoneInfo("Europe/London"))


def plain_job() -> bytes:
    return encode([Line("Hello"), Line("Bold", bold=True), Line("Centre", align="center")])


def raster_job() -> bytes:
    return encode([Line("", raster=(64, 64, sparkline_bitmap([1.0, 4.0, 2.0, 6.0, 3.0])))])


def receipt_job() -> bytes:
    receipt = Receipt(recipient="Yannic", sender="hermes", title="Dinner", message="Pasta is ready.", sent_at=SENT)
    return encode(render_lines(receipt, 42))


CASES = {"plain.bin": plain_job, "raster.bin": raster_job, "receipt.bin": receipt_job}


def test_text_sequence_is_exact():
    payload = plain_job()
    assert payload.startswith(INITIALIZE + CODE_PAGE_CP437)
    assert ALIGN["left"] + BOLD_OFF + TALL_OFF + b"Hello" + LF in payload
    assert ALIGN["left"] + BOLD_ON + TALL_OFF + b"Bold" + LF in payload
    assert ALIGN["center"] + BOLD_OFF + TALL_OFF + b"Centre" + LF in payload
    assert payload.endswith(FEED_LINES + bytes([4]) + PARTIAL_CUT)


def test_raster_sequence_is_exact():
    payload = raster_job()
    header = GS + b"v0\x00" + bytes([64, 0, 64, 0])  # GS v 0 m=0, 64 bytes per row, 64 rows
    assert header in payload
    data_start = payload.index(header) + len(header)
    image = sparkline_bitmap([1.0, 4.0, 2.0, 6.0, 3.0])
    assert payload[data_start : data_start + 64 * 64] == image
    assert payload[data_start + 64 * 64 :].startswith(TALL_OFF + BOLD_OFF + ALIGN["left"])


def test_cut_sequence_is_partial_feed_then_cut():
    assert PARTIAL_CUT == b"\x1dV\x01"
    assert receipt_job().endswith(b"\x1bd\x04\x1dV\x01")


def test_golden_files_match():
    for name, make in CASES.items():
        expected = (GOLDEN / name).read_bytes()
        assert make() == expected, f"{name} changed; run: python -m tests.test_golden --regenerate"


if __name__ == "__main__" and "--regenerate" in sys.argv:
    GOLDEN.mkdir(exist_ok=True)
    for name, make in CASES.items():
        (GOLDEN / name).write_bytes(make())
        print("wrote", GOLDEN / name)
