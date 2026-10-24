"""1-bit drawing canvas for receipt designs. A port of design-lab/lib/raster.js.

Every drawing call matches the Node renderer, so the same design gives the same bits. The
Node renderer is the reference: tests compare against bitmaps it produced.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.render.glyphs import GLYPHS

PAPER_DOTS = 512  # 80 mm paper, 512 dots wide
MAX_HEIGHT = 2400
ROW_BYTES = PAPER_DOTS // 8


def js_round(value: float) -> int:
    """JavaScript Math.round: halves go up, so 2.5 is 3 and -2.5 is -2."""
    return math.floor(value + 0.5)


def text_width(text: str, scale: int) -> int:
    return len(text) * 6 * scale - scale


@dataclass(frozen=True)
class Mark:
    """An ornament piece: its size and the ink pixels, relative to its top-left corner."""

    width: int
    height: int
    ink: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class Bitmap:
    width: int
    height: int
    bits: bytes  # rows of ROW_BYTES bytes, MSB first, 1 = black


class Canvas:
    def __init__(self) -> None:
        self.bits = bytearray(ROW_BYTES * MAX_HEIGHT)
        self.y = 0

    # ---- pixels ------------------------------------------------------------------------
    def set_px(self, x: int, y: int) -> None:
        if x < 0 or y < 0 or x >= PAPER_DOTS or y >= MAX_HEIGHT:
            return
        self.bits[y * ROW_BYTES + (x >> 3)] |= 0x80 >> (x & 7)

    def fill_rect(self, x: int, y: int, w: int, h: int) -> None:
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                self.set_px(xx, yy)

    def draw_line(self, x0: int, y0: int, x1: int, y1: int) -> None:
        steps = max(abs(x1 - x0), abs(y1 - y0), 1)
        for t in range(steps + 1):
            self.set_px(js_round(x0 + ((x1 - x0) * t) / steps), js_round(y0 + ((y1 - y0) * t) / steps))

    def stamp(self, mark: Mark, x: int, y: int) -> None:
        for dx, dy in mark.ink:
            self.set_px(x + dx, y + dy)

    # ---- text --------------------------------------------------------------------------
    def glyph_dots(self, x: int, y: int, text: str, scale: int) -> list[tuple[int, int, int, int]]:
        """The ink squares of a line of text, as (x, y, w, h). Used to draw it and to erase it again.

        Scales that are a multiple of 3 use the printed dot style: each dot is a 2 x 2 square on a
        3-dot pitch (design system tokens, dot style). Other scales draw solid dots.
        """
        squares: list[tuple[int, int, int, int]] = []
        cx = x
        for ch in text:
            glyph = GLYPHS.get(ch.upper(), GLYPHS["?"])
            for r in range(7):
                for c in range(5):
                    if glyph[r][c] != "#":
                        continue
                    ox, oy = cx + c * scale, y + r * scale
                    if scale % 3 == 0:
                        for i in range(scale // 3):
                            for j in range(scale // 3):
                                squares.append((ox + i * 3, oy + j * 3, 2, 2))
                    else:
                        squares.append((ox, oy, scale, scale))
            cx += 6 * scale
        return squares

    def text(self, x: int, y: int, text: str, scale: int = 2) -> int:
        """Dot-matrix text. Returns the advance width."""
        for sx, sy, w, h in self.glyph_dots(x, y, text, scale):
            self.fill_rect(sx, sy, w, h)
        return 6 * scale * len(text)

    def text_in(self, x0: int, x1: int, y: int, text: str, scale: int = 2) -> None:
        self.text(x0 + (x1 - x0 - text_width(text, scale)) // 2, y, text, scale)

    def text_right(self, x1: int, y: int, text: str, scale: int = 2) -> None:
        self.text(x1 - text_width(text, scale), y, text, scale)

    # ---- shapes ------------------------------------------------------------------------
    def hline(self, x0: int, x1: int, y: int, t: int = 1) -> None:
        self.fill_rect(x0, y, x1 - x0, t)

    def vline(self, x: int, y0: int, y1: int, t: int = 1) -> None:
        self.fill_rect(x, y0, t, y1 - y0)

    def round_box(self, x0: int, y0: int, x1: int, y1: int, r: int = 10, t: int = 2) -> None:
        """Rounded outline with corner radius r and stroke t."""
        self.hline(x0 + r, x1 - r, y0, t)
        self.hline(x0 + r, x1 - r, y1 - t, t)
        self.vline(x0, y0 + r, y1 - r, t)
        self.vline(x1 - t, y0 + r, y1 - r, t)
        for a in range(0, 91, 2):
            rad = math.radians(a)
            dx = js_round(math.cos(rad) * r)
            dy = js_round(math.sin(rad) * r)
            self.fill_rect(x0 + r - dx, y0 + r - dy, t, t)
            self.fill_rect(x1 - r + dx - t + 1, y0 + r - dy, t, t)
            self.fill_rect(x0 + r - dx, y1 - r + dy - t + 1, t, t)
            self.fill_rect(x1 - r + dx - t + 1, y1 - r + dy - t + 1, t, t)

    def fill(self, x0: int, y0: int, x1: int, y1: int) -> None:
        self.fill_rect(x0, y0, x1 - x0, y1 - y0)

    def seg_bar(self, x0: int, x1: int, y: int, h: int, fraction: float, segs: int = 10) -> None:
        """Segmented bar: solid segments for the fraction, dotted empty ones."""
        gap = 4
        seg = (x1 - x0 - gap * (segs - 1)) // segs
        on = js_round(fraction * segs)
        for i in range(segs):
            sx = x0 + i * (seg + gap)
            if i < on:
                self.fill_rect(sx, y, seg, h)
            else:
                self.dotted_box(sx, y, sx + seg, y + h)

    def dotted_box(self, x0: int, y0: int, x1: int, y1: int) -> None:
        for y in range(y0, y1, 2):
            for x in range(x0, x1, 2):
                self.set_px(x, y)

    # ---- rows --------------------------------------------------------------------------
    def row(self, x0: int, x1: int, y: int, label: str, value: object, scale: int = 2) -> None:
        """Label, dot leaders, then the value right-aligned at x1."""
        tail = str(value)
        total = text_width(label, scale) + text_width(tail, scale) + 2 * 6 * scale
        dots_w = x1 - x0 - total
        dot_count = max(1, dots_w // (2 * scale))
        self.text(x0, y, label, scale)
        dx = x0 + text_width(label, scale) + 6 * scale
        for i in range(dot_count):
            self.fill_rect(dx + i * 2 * scale, y + 6 * scale, scale, scale)
        self.text_right(x1, y, tail, scale)

    # ---- output ------------------------------------------------------------------------
    def crop(self, margin: int = 12) -> Bitmap:
        """The drawn area plus a small margin, as the printed image."""
        height = min(MAX_HEIGHT, self.y + margin)
        return Bitmap(PAPER_DOTS, height, bytes(self.bits[: ROW_BYTES * height]))
