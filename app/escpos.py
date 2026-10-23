"""ESC/POS encoding for the Epson TM-T88V on 80 mm paper (Font A, 48 columns)."""

from __future__ import annotations

from app.receipt import Line

ESC = b"\x1b"
GS = b"\x1d"
LF = b"\n"

INITIALIZE = ESC + b"@"
CODE_PAGE_CP437 = ESC + b"t\x00"
BOLD_ON = ESC + b"E\x01"
BOLD_OFF = ESC + b"E\x00"
TALL_ON = GS + b"!\x01"  # double height, normal width
TALL_OFF = GS + b"!\x00"
ALIGN = {"left": ESC + b"a\x00", "center": ESC + b"a\x01"}
FEED_LINES = ESC + b"d"  # ESC d n: print and feed n lines
PARTIAL_CUT = GS + b"V\x01"  # GS V 1: partial cut


def encode(lines: list[Line], feed: int = 4) -> bytes:
    """Return the byte stream for one receipt, ending with a feed and a partial cut."""
    out = bytearray(INITIALIZE + CODE_PAGE_CP437)
    for line in lines:
        out += ALIGN[line.align]
        out += BOLD_ON if line.bold else BOLD_OFF
        out += TALL_ON if line.tall else TALL_OFF
        # cp437 is what the printer's default code page understands. Anything else
        # becomes "?" rather than corrupting the rest of the job.
        out += line.text.encode("cp437", errors="replace") + LF
    out += TALL_OFF + BOLD_OFF + ALIGN["left"]
    out += FEED_LINES + bytes([max(0, min(feed, 255))]) + PARTIAL_CUT
    return bytes(out)


def to_text(lines: list[Line], width: int = 48) -> str:
    """Plain-text rendering for previews. Bold and size are not shown."""
    rows = [
        line.text.center(width).rstrip() if line.align == "center" else line.text
        for line in lines
    ]
    return "\n".join(rows) + "\n"
