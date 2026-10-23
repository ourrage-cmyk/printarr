"""ESC/POS encoding for the Epson TM-T88V on 80 mm paper (Font A, 42 columns)."""

from __future__ import annotations

from app.receipt import Line

ESC = b"\x1b"
GS = b"\x1d"
LF = b"\n"

INITIALIZE = ESC + b"@"
CODE_PAGE_CP437 = ESC + b"t\x00"
BOLD_ON = ESC + b"E\x01"
BOLD_OFF = ESC + b"E\x00"
# GS ! n: bits 0-2 = height multiplier minus 1, bits 4-6 = width multiplier minus 1.
# The TRG confirms double size exists but not these bits. UNVERIFIED against the
# Command Reference (Epson download4.epson.biz, ESC/POS reference).
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
        if line.raster is not None:
            # GS v 0 m xL xH yL yH: print a 1-bit raster image, m=0 normal density.
            width_bytes, height, data = line.raster
            out += GS + b"v0\x00" + bytes([width_bytes & 0xFF, width_bytes >> 8, height & 0xFF, height >> 8])
            out += data
            continue
        out += BOLD_ON if line.bold else BOLD_OFF
        out += TALL_ON if line.tall else TALL_OFF
        # cp437 is what the printer's default code page understands. Anything else
        # becomes "?" rather than corrupting the rest of the job.
        out += line.text.encode("cp437", errors="replace") + LF
    out += TALL_OFF + BOLD_OFF + ALIGN["left"]
    out += FEED_LINES + bytes([max(0, min(feed, 255))]) + PARTIAL_CUT
    return bytes(out)


def to_text(lines: list[Line], width: int = 42) -> str:
    """Plain-text rendering for previews. Bold and size are not shown."""
    rows: list[str] = []
    for line in lines:
        rows.append(line.text.center(width).rstrip() if line.align == "center" else line.text)
        if line.raster is not None:
            rows.append("[graph]".center(width).rstrip())
    return "\n".join(rows) + "\n"
