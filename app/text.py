"""Make text printable on the TM-T88V.

The printer's default code page is CP437. Characters CP437 lacks are handled in order:

1. Common typography (smart quotes, dashes, ellipsis, bullets) becomes plain ASCII.
2. Accented letters that CP437 lacks lose their accent (ā becomes a, ş becomes s).
3. A line that still has characters CP437 lacks is printed as an image, drawn with the
   bundled Noto Sans (SIL Open Font License, see app/fonts/OFL.txt). This covers Latin,
   Greek and Cyrillic names. It is used only when the font has every such character.
4. Anything else (CJK, Arabic, emoji) prints as "?". The preview lists those characters.
"""

from __future__ import annotations

import math
import unicodedata
from functools import lru_cache
from pathlib import Path

from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont

FONT_PATH = Path(__file__).parent / "fonts" / "NotoSans-Regular.ttf"
PAPER_DOTS = 512  # TM-T88V, 80 mm paper
GLYPH_SIZE = 24  # pixels at full size, close to Font A's height
GLYPH_BYTES = PAPER_DOTS // 8

TRANSLIT = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"',
    "–": "-", "—": "-", "−": "-",
    "…": "...", " ": " ", "•": "*",
}


def _in_cp437(ch: str) -> bool:
    try:
        ch.encode("cp437")
    except UnicodeEncodeError:
        return False
    return True


def transliterate(text: str) -> str:
    """Replace typography and accents that CP437 lacks. Other characters are left alone."""
    out: list[str] = []
    for ch in text:
        if ch in TRANSLIT:
            out.append(TRANSLIT[ch])
        elif _in_cp437(ch):
            out.append(ch)
        else:
            base = "".join(c for c in unicodedata.normalize("NFKD", ch) if not unicodedata.combining(c))
            out.append(base if base and all(_in_cp437(c) for c in base) else ch)
    return "".join(out)


@lru_cache(maxsize=1)
def _font_coverage() -> frozenset[int]:
    return frozenset(TTFont(FONT_PATH).getBestCmap())


def printable(text: str) -> tuple[str, bool]:
    """Return (text to send as CP437, whether the line must be drawn as a glyph image)."""
    text = transliterate(text)
    if all(_in_cp437(ch) for ch in text):
        return text, False
    coverage = _font_coverage()
    if all(_in_cp437(ch) or ord(ch) in coverage for ch in text):
        return text, True
    # Some character has no glyph in the bundled font: print the whole line in CP437.
    return "".join(ch if _in_cp437(ch) else "?" for ch in text), False


def printed_as_question(text: str) -> list[str]:
    """Characters in this line that will print as "?" on the printer."""
    _, glyph = printable(text)
    if glyph:
        return []
    return sorted({ch for ch in transliterate(text) if not _in_cp437(ch)})


@lru_cache(maxsize=256)
def glyph_raster(text: str, align: str = "left") -> tuple[int, int, bytes]:
    """Draw one line of text as a 512-dot-wide 1-bit image. Long lines shrink to fit."""
    size = GLYPH_SIZE
    font = ImageFont.truetype(str(FONT_PATH), size)
    width = font.getlength(text)
    if width > PAPER_DOTS:
        size = max(8, math.floor(GLYPH_SIZE * PAPER_DOTS / width))
        font = ImageFont.truetype(str(FONT_PATH), size)
        width = font.getlength(text)
    height = math.ceil(size * 1.5)
    x = 0 if align == "left" else max(0, (PAPER_DOTS - width) // 2)
    image = Image.new("1", (PAPER_DOTS, height), 1)  # 1 is white in Pillow
    ImageDraw.Draw(image).text((x, 0), text, font=font, fill=0)
    # The printer treats 1 as a black dot, so invert the packed bytes.
    data = bytes(b ^ 0xFF for b in image.tobytes())
    return GLYPH_BYTES, height, data
