"""ESC/POS encoding for the Epson TM-T88V on 80 mm paper (Font A, 42 columns)."""

from __future__ import annotations

from app.receipt import Line
from app.text import glyph_raster, printable

ESC = b"\x1b"
GS = b"\x1d"
LF = b"\n"

INITIALIZE = ESC + b"@"
CODE_PAGE_CP437 = ESC + b"t\x00"
BOLD_ON = ESC + b"E\x01"
BOLD_OFF = ESC + b"E\x00"
# GS ! n: bits 0-2 = height multiplier minus 1, bits 4-6 = width multiplier minus 1
# (Command Reference, gs_exclamation). 0x01 is double height.
TALL_ON = GS + b"!\x01"  # double height, normal width
TALL_OFF = GS + b"!\x00"
ALIGN = {"left": ESC + b"a\x00", "center": ESC + b"a\x01"}
FEED_LINES = ESC + b"d"  # ESC d n: print and feed n lines
PARTIAL_CUT = GS + b"V\x01"  # GS V 1: partial cut, Function A (Command Reference, gs_cv)
PRINT_BUFFER = GS + b"(L\x02\x00\x30\x32"  # GS ( L, m=48, fn=50: print graphics in buffer

# Raster images. "gs_l" is GS ( L function 112, the current form. "gs_v0" is the
# obsolete GS v 0 form, kept behind PRINTARR_RASTER_MODE in case a unit rejects fn 112.
RASTER_GS_L = "gs_l"
RASTER_GS_V0 = "gs_v0"
RASTER_MODES = (RASTER_GS_L, RASTER_GS_V0)


def _u16(value: int) -> bytes:
    return bytes([value & 0xFF, value >> 8])


MAX_BAND_ROWS = 1000  # a GS ( L block holds at most 65535 bytes: a 64-byte row allows 1023 rows, so a tall picture goes in bands


def _raster(width_bytes: int, height: int, data: bytes, mode: str) -> bytes:
    if height > MAX_BAND_ROWS:
        out = b""
        for top in range(0, height, MAX_BAND_ROWS):
            rows = min(MAX_BAND_ROWS, height - top)
            out += _raster(width_bytes, rows, data[top * width_bytes:(top + rows) * width_bytes], mode)
        return out
    if mode == RASTER_GS_V0:
        return GS + b"v0\x00" + _u16(width_bytes) + _u16(height) + data
    # GS ( L pL pH 48 112 a bx by c xL xH yL yH d...: monochrome, 1x scale, colour 49.
    # xL/xH count dots across (8 per byte), yL/yH count rows. pL/pH count the bytes after them.
    body = bytes([48, 112, 48, 1, 1, 49]) + _u16(width_bytes * 8) + _u16(height)
    return GS + b"(L" + _u16(len(body) + len(data)) + body + data + PRINT_BUFFER


def encode(lines: list[Line], feed: int = 4, raster_mode: str = RASTER_GS_L) -> bytes:
    """Return the byte stream for one receipt, ending with a feed and a partial cut."""
    if raster_mode not in RASTER_MODES:
        raise ValueError(f"raster mode must be one of {RASTER_MODES}")
    out = bytearray(INITIALIZE + CODE_PAGE_CP437)
    for line in lines:
        out += ALIGN[line.align]
        if line.raster is not None:
            width_bytes, height, data = line.raster
            out += _raster(width_bytes, height, data, raster_mode)
            continue
        text, as_glyph = printable(line.text)
        if as_glyph:
            # Names outside CP437 (Cyrillic, Greek, accented Latin the code page lacks)
            # print as a drawn line, so they are readable rather than "?".
            width_bytes, height, data = glyph_raster(text, line.align)
            out += _raster(width_bytes, height, data, raster_mode)
            continue
        out += BOLD_ON if line.bold else BOLD_OFF
        out += TALL_ON if line.tall else TALL_OFF
        # Anything still outside CP437 becomes "?" rather than corrupting the rest of the job.
        out += text.encode("cp437", errors="replace") + LF
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
