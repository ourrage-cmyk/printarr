"""Composable receipt strips on a 3-column grid, drawn as 1-bit bitmaps.

A strip is an ordered list of blocks. Every block is a card. Cards are 3 units wide (the full paper
width) or narrower, and tall in whole units. Short blocks can sit side by side, for example 1 + 2 or
1 + 1 + 1. Text blocks are fluid: they measure their content and take the height in whole units they
need, within a min and a max. Anything beyond the max is shortened with "..." so cards never overlap.

Rules, from design-system/blocks.json:
- one ornament per card
- at most five blocks per strip, and a greeting always starts a new strip
- blank margins at the top and bottom of each strip, for a clean cut
- moods change the ornament, icon and accent only

Port of the grid in receipt-lab/lib/blocks.js (the Node reference). Keep the constants in step.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.render.canvas import Bitmap, Canvas, js_round, solid_width, text_width
from app.render.system import ornament

CATALOGUE: dict[str, Any] = json.loads((Path(__file__).parent / "system" / "blocks.json").read_text())
SHELL: dict[str, Any] = CATALOGUE["shell"]
GRID: dict[str, int] = CATALOGUE["grid"]
MOODS: dict[str, dict[str, str]] = CATALOGUE["moods"]
BLOCKS: dict[str, dict[str, Any]] = CATALOGUE["blocks"]

BODY = 3  # body and label scale: cap 21 (conformance, font arena tier B)
ROW = 7 * BODY + 9  # one row of text: cap 21 with the tokens' body leading of 9 dots
CAPTION = 2  # caption scale: cap 14, the minimum
NUMERAL = 6  # display numerals: cap 42, used when the value fits the tile
TITLE = 4  # titles that do not fit one line at NUMERAL: cap 28, still larger than body (cap 21)
GRAPH_PLOT = 56  # a graph is 56 dots tall, as the catalogue says, so its height does not depend on the card

UNIT_H = GRID["unit_h"]  # one unit of height, in dots
GAP_V = GRID["gap_v"]  # space between rows of cards
PAD_V = GRID["pad_v"]  # card padding, top and bottom
PAD_H = GRID["pad_h"]  # card padding, left and right
COLS = GRID["cols"]
COL_GAP = GRID["col_gap"]
OUTER_L = GRID["outer_l"]
OUTER_R = GRID["outer_r"]
CELL_W = (OUTER_R - OUTER_L - (COLS - 1) * COL_GAP) // COLS
RADIUS = SHELL["radius_dots"]
STROKE = SHELL["stroke_dots"]
MAX_BLOCKS = SHELL["strip_rules"]["max_blocks"]
MARGIN_TOP = SHELL["margins"]["top_dots"]
MARGIN_BOTTOM = SHELL["margins"]["bottom_dots"]
NEUTRAL = "neutral"

# The card outline says the tone before a word is read: urgent tones draw a heavier, squarer outline,
# soft tones a rounder one. Tones not listed use the shell's own stroke and radius.
STROKE_BY_MOOD: dict[str, int] = {"urgent": 4, "critical": 5, "upset": 4, "firm_complaint": 3}
RADIUS_BY_MOOD: dict[str, int] = {"urgent": 2, "critical": 2, "upset": 2, "firm_complaint": 2, "loving": 12, "gentle_warning": 12, "playful": 12, "happy": 8}

# Layout per block type: span in columns and height in units. Text is fluid; metric tiles are fluid up to 3.
LAYOUT: dict[str, dict[str, int]] = {
    "greeting": {"span": 3, "min_span": 3, "min_units": 1, "max_units": 6},
    "metric": {"span": 1, "min_span": 1, "min_units": 2, "max_units": 5},
    "metric_rows": {"span": 3, "min_span": 2, "min_units": 2, "max_units": 8},
    "graph": {"span": 3, "min_span": 2, "min_units": 3, "max_units": 8},
    "dog_counts": {"span": 3, "min_span": 2, "min_units": 2, "max_units": 6},
    "message": {"span": 3, "min_span": 2, "min_units": 2, "max_units": 16},
    "alert": {"span": 3, "min_span": 2, "min_units": 2, "max_units": 8},
    "checklist": {"span": 3, "min_span": 2, "min_units": 2, "max_units": 10},
    "tip": {"span": 3, "min_span": 2, "min_units": 1, "max_units": 6},
    "fact": {"span": 3, "min_span": 2, "min_units": 2, "max_units": 6},
}

# ---- icon sprites, 3 dots per sprite pixel (copied from receipt-lab/lib/raster.js) ----------
SPRITES: dict[str, tuple[str, ...]] = {
    "sun": ("....#....", "..#.#.#..", "...###...", ".#######.", "#########", ".#######.", "...###...", "..#.#.#..", "....#...."),
    "bone": ("##.....##", "###...###", "...###...", "###...###", "##.....##"),
    "battery": ("##########", "#........#", "#........#", "#........#", "##########"),
    "bolt": ("....##.", "...##..", "..##...", ".#####.", "....##.", "...##..", "..##...", ".##....", "##....."),
    "thermo": ("..#..", "..#..", "..#..", "..#..", ".###.", "#####", "#####", ".###."),
    "cloud": ("...###....", ".#########.", "###########", "###########", ".#########."),
    "walk": ("..##.", ".###.", "..#..", ".###.", "#..#.", ".##..", "#..#."),
    "heart": (".##.##.", "#######", "#######", ".#####.", "..###..", "...#..."),
    "drop": ("..#..", ".###.", "#####", "#####", ".###."),
    "box": ("#####", "#...#", "#...#", "#...#", "#####"),
    "check": ("......#", ".....##", "#...##.", "##.##..", ".###...", "..#...."),
    "star": ("....#....", "....#....", "#########", ".#######.", "..#####..", ".##.#.##.", "##.....##", ".........", "........."),
    "warn": ("....#....", "...###...", "...###...", "..##.##..", "..##.##..", ".##...##.", ".##...##.", "#########", "........."),
    "question": (".###.", "#...#", "....#", "...#.", "..#..", ".....", "..#.."),
    # kind marks: one per kind of ticket, stamped at the card's top-right corner
    "cart": ("##.......", ".#.......", ".#######.", ".#.#.#.#.", "..#####..", "..#...#..", "..##.##.."),
    "clock": ("..#####..", ".#.....#.", "#...#...#", "#...#...#", "#...###.#", "#.......#", ".#.....#.", "..#####.."),
    "bulb": ("..###..", ".#...#.", "#.....#", "#.....#", ".#...#.", "..###..", "..###..", "..###.."),
    "bell": ("...#...", "..###..", ".#####.", ".#####.", "#######", "#######", "...#..."),
    "envelope": ("#########", "##.....##", "#.#...#.#", "#..###..#", "#.......#", "#########"),
}

# The mark each block type wears, so a note, an alert, a reminder, a fun fact and a shopping list
# are told apart at a glance by something other than their words. Tones change the header and the
# icon; the kind mark is separate and sits at the top-right.
URGENT_MOODS = {"urgent", "critical", "firm_complaint", "upset"}
KIND_MARKS: dict[str, str] = {"message": "envelope", "alert": "bolt", "checklist": "cart", "tip": "clock", "fact": "bulb"}


def stamp_sprite(c: Canvas, x: int, y: int, name: str, scale: int = 3) -> None:
    for r, row in enumerate(SPRITES[name]):
        for col, ch in enumerate(row):
            if ch == "#":
                c.fill_rect(x + col * scale, y + r * scale, scale, scale)


def _kind_mark(card: "Card", kind: str, x1: int) -> int:
    """Stamps the kind mark at the card's top-right corner. Returns the width the text beside it must leave."""
    name = KIND_MARKS.get(kind)
    if kind == "alert" and card.mood not in URGENT_MOODS:
        name = "bell"  # a bolt says urgent; a gentle heads-up must not look urgent
    if name is None or name in card.marked:
        return 0
    card.marked.add(name)
    width = len(SPRITES[name][0]) * 3
    stamp_sprite(card.c, x1 - width, card.c.y, name)
    return width + 8


# ---- ornaments: each draws across x0..x1 at y and returns the height it used ------------------
def _sun_strip(c: Canvas, x0: int, x1: int, y: int) -> int:
    cx = (x0 + x1) // 2
    # The arc stops 2 dots above the rule, so the sun sits on it without touching or crossing it.
    for a in range(180, 361, 4):
        rad = math.radians(a)
        c.fill_rect(js_round(cx + math.cos(rad) * 14) - 1, js_round(y + 14 + math.sin(rad) * 14) - 1, 3, 3)
    c.fill_rect(x0, y + 16, x1 - x0, 2)
    return 18


def _dotted_wave(c: Canvas, x0: int, x1: int, y: int) -> int:
    amp = 3
    for x in range(x0, x1, 3):
        c.set_px(x, js_round(y + amp + math.sin((x - x0) / 6) * amp))
    return amp * 2 + 2


def _star_row(c: Canvas, x0: int, x1: int, y: int) -> int:
    """Small plus-shaped stars along the width: playful."""
    for x in range(x0 + 4, x1 - 4, 14):
        c.fill_rect(x, y + 4, 7, 2)
        c.fill_rect(x + 2, y + 1, 2, 8)
    return 10


def _burst(c: Canvas, x0: int, x1: int, y: int) -> int:
    """Tall and short strokes alternating, like a cheer: excited."""
    for k, x in enumerate(range(x0, x1, 6)):
        c.fill_rect(x, y + (0 if k % 2 == 0 else 5), 2, 12 if k % 2 == 0 else 4)
    return 12


def _dot_dash(c: Canvas, x0: int, x1: int, y: int) -> int:
    """Dot, dot, dash: confused."""
    x = x0
    while x < x1:
        c.fill_rect(x, y + 3, 2, 2)
        c.fill_rect(x + 6, y + 3, 2, 2)
        c.fill_rect(x + 14, y + 3, 8, 2)
        x += 30
    return 8


def _barcode(c: Canvas, x0: int, x1: int, y: int) -> int:
    widths = [2, 1, 3, 1, 1, 2, 4, 1, 2, 1, 3, 2, 1, 1, 2, 3, 1, 2]
    x = x0
    i = 0
    while x < x1:
        w = widths[i % len(widths)]
        i += 1
        c.fill_rect(x, y, w, 10)
        x += w + 2
    return 10


def _tape_ticks(c: Canvas, x0: int, x1: int, y: int) -> int:
    c.fill_rect(x0, y, x1 - x0, 1)
    for i, x in enumerate(range(x0, x1 + 1, 8)):
        c.fill_rect(x, y, 1, 8 if i % 5 == 0 else 4)
    return 9


def _perforation(c: Canvas, x0: int, x1: int, y: int) -> int:
    for x in range(x0, x1, 10):
        c.fill_rect(x, y, 6, 2)
    return 2


def _dashed_rule(c: Canvas, x0: int, x1: int, y: int) -> int:
    for x in range(x0, x1, 8):
        c.fill_rect(x, y, 4, 1)
    return 1


def _hairline(c: Canvas, x0: int, x1: int, y: int) -> int:
    c.fill_rect(x0, y, x1 - x0, 1)
    return 1


def _double_hairline(c: Canvas, x0: int, x1: int, y: int) -> int:
    c.fill_rect(x0, y, x1 - x0, 1)
    c.fill_rect(x0, y + 3, x1 - x0, 1)
    return 4


def _heart(c: Canvas, x0: int, x1: int, y: int) -> int:
    stamp_sprite(c, (x0 + x1 - len(SPRITES["heart"][0]) * 3) // 2, y, "heart")
    return 18


def _warn(c: Canvas, x0: int, _x1: int, y: int) -> int:
    stamp_sprite(c, x0, y, "warn")
    return 24


BAND_H = 20  # a mood band is tall enough to read at a glance, before a word is read


def _band_dots(c: Canvas, x0: int, x1: int, y: int) -> int:
    """Warm family: two rows of sparse round dots, offset like a soft pattern."""
    for row, yy in enumerate((y + 4, y + 12)):
        for x in range(x0 + 4 + (6 if row else 0), x1 - 4, 12):
            c.fill_rect(x, yy, 4, 4)
    return BAND_H


def _band_zigzag(c: Canvas, x0: int, x1: int, y: int) -> int:
    """Energetic family: a bold zigzag."""
    prev = None
    for x in range(x0, x1):
        phase = (x - x0) % 16
        yy = y + 2 + (phase if phase < 8 else 16 - phase) * 2
        for dy in range(0, 4):
            c.set_px(x, min(y + BAND_H - 1, yy + dy))
        if prev is not None:
            for t in range(min(yy, prev), max(yy, prev) + 1):
                c.set_px(x, t)
        prev = yy
    return BAND_H


def _band_ticks(c: Canvas, x0: int, x1: int, y: int) -> int:
    """Prompt family: evenly spaced upright ticks, a pause cue."""
    for x in range(x0 + 2, x1 - 2, 8):
        c.fill_rect(x, y + 2, 3, BAND_H - 4)
    return BAND_H


def _band_fill(c: Canvas, x0: int, x1: int, y: int) -> int:
    """Critical: a solid black bar."""
    c.fill_rect(x0, y, x1 - x0, BAND_H)
    return BAND_H


def _band_stipple(c: Canvas, x0: int, x1: int, y: int) -> int:
    """Heavy family: a dense stippled bar, the most ink after the barcode."""
    for yy in range(y, y + BAND_H, 4):
        for x in range(x0 + (yy - y) % 8 // 2, x1 - 1, 4):
            c.fill_rect(x, yy, 2, 2)
    return BAND_H


def _band_hatch(c: Canvas, x0: int, x1: int, y: int) -> int:
    """Caution family: diagonal hatching between two rules."""
    c.fill_rect(x0, y, x1 - x0, 2)
    c.fill_rect(x0, y + BAND_H - 2, x1 - x0, 2)
    for x in range(x0, x1):
        for yy in range(y + 3, y + BAND_H - 3):
            if (x - x0 + (yy - y)) % 10 < 3:
                c.set_px(x, yy)
    return BAND_H


def _band_barcode(c: Canvas, x0: int, x1: int, y: int) -> int:
    """Urgent family: a tall barcode."""
    widths = [2, 1, 3, 1, 1, 2, 4, 1, 2, 1, 3, 2, 1, 1, 2, 3, 1, 2]
    x = x0
    i = 0
    while x < x1:
        w = min(widths[i % len(widths)], x1 - x)
        i += 1
        c.fill_rect(x, y, w, BAND_H)
        x += w + 2
    return BAND_H


ORNAMENTS: dict[str, Callable[[Canvas, int, int, int], int]] = {
    "bandDots": _band_dots,
    "bandZigzag": _band_zigzag,
    "bandTicks": _band_ticks,
    "bandFill": _band_fill,
    "bandStipple": _band_stipple,
    "bandHatch": _band_hatch,
    "bandBarcode": _band_barcode,
    "sunStrip": _sun_strip,
    "dottedWave": _dotted_wave,
    "starRow": _star_row,
    "burst": _burst,
    "dotDash": _dot_dash,
    "barcode": _barcode,
    "tapeTicks": _tape_ticks,
    "perforation": _perforation,
    "dashedRule": _dashed_rule,
    "hairline": _hairline,
    "doubleHairline": _double_hairline,
    "heart": _heart,
    "warn": _warn,
}


# Mood ornament names mapped to the 26 system pieces (app/render/system/ornaments). Names without a
# piece, such as the hairlines, keep their drawing in code.
SYSTEM_PIECES: dict[str, str] = {
    "sunStrip": "sys-sun-strip",
    "dottedWave": "sys-wave",
    "barcode": "sys-barcode-decor",
    "tapeTicks": "sys-tape-ticks",
    "perforation": "sys-perforation",
    "dashedRule": "sys-dotted-rule",
    "heart": "sys-heart",
    "warn": "sys-warning",
}


# ---- text helpers --------------------------------------------------------------------------------
def _label(text: object) -> str:
    """Upper case, with underscores as spaces: the dot font has no underscore."""
    return str(text).upper().replace("_", " ")


def solid_wrap(text: str, max_w: int) -> list[str]:
    """Word-wrap full-line body text by its real width in Inter, so no line runs past the card."""
    from app.render.canvas import solid_width

    lines: list[str] = []
    cur = ""
    for word in text.split():
        while solid_width(word, 21) > max_w and len(word) > 1:  # a URL or code wider than the line breaks by character
            cut = max(1, next((i for i in range(len(word), 0, -1) if solid_width(word[:i], 21) <= max_w), 1))
            if cur:
                lines.append(cur)
                cur = ""
            lines.append(word[:cut])
            word = word[cut:]
        trial = f"{cur} {word}" if cur else word
        if cur and solid_width(trial, 21) > max_w:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


def wrap_lines(text: str, scale: int, max_w: int) -> list[str]:
    if scale == BODY:
        return solid_wrap(text, max_w)
    per_line = max(1, max_w // (6 * scale))
    lines: list[str] = []
    cur = ""
    for word in text.upper().split():
        if cur and len(cur) + 1 + len(word) > per_line:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}" if cur else word
    if cur:
        lines.append(cur)
    return lines


PARA_GAP = 10  # the blank between two paragraphs of authored text, in dots


def _paragraph_lines(text: str, scale: int, max_w: int) -> list[list[str]]:
    """The wrapped lines of each paragraph. A blank line in the source starts a new paragraph."""
    parts = [part for part in re.split(r"\n\s*\n", str(text)) if part.strip()] or [""]
    return [wrap_lines(part, scale, max_w) for part in parts]


def paragraph(c: Canvas, x: int, y: int, text: str, scale: int, max_w: int) -> int:
    step = 7 * scale + 4
    top = y
    for para in _paragraph_lines(text, scale, max_w):
        for line in para:
            if scale == BODY:
                c.solid(x, y, line, 21)  # body text is full-line (Inter), not dot matrix
            else:
                c.text(x, y, line, scale)
            y += step
        y += PARA_GAP
    return y - top - PARA_GAP


def paragraph_height(text: str, scale: int, max_w: int) -> int:
    paras = _paragraph_lines(text, scale, max_w)
    return sum(len(para) for para in paras) * (7 * scale + 4) + PARA_GAP * (len(paras) - 1)


def line_graph(c: Canvas, x0: int, y0: int, x1: int, y1: int, values: Sequence[float]) -> None:
    lo = min(values)
    hi = max(values)
    span = (hi - lo) or 1
    pad = 4
    n = len(values)
    pts = [
        (
            js_round(x0 + pad + (i * (x1 - x0 - pad * 2)) / (n - 1)),
            js_round(y1 - pad - ((v - lo) / span) * (y1 - y0 - pad * 2)),
        )
        for i, v in enumerate(values)
    ]
    for g in range(4):
        gy = y0 + js_round((g * (y1 - y0)) / 3)
        for x in range(x0, x1, 4):
            c.set_px(x, gy)
    c.vline(x0, y0, y1 + 1, 1)
    c.hline(x0, x1, y1, 1)
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        c.draw_line(ax, ay, bx, by)
        c.draw_line(ax, ay + 1, bx, by + 1)
    for x, y in pts[::6]:
        c.fill_rect(x - 2, y - 2, 5, 5)


# ---- per-card drawing state -----------------------------------------------------------------------
@dataclass
class Card:
    """The canvas and the card's ornament state. One ornament per card: the first one asked for wins."""

    c: Canvas
    mood: str
    ornamented: bool = False
    plot_h: int = 56  # graph height, set from the card's height
    in_group: bool = False  # the card holds several regions: a tip leads with its icon instead of centring
    fact_labeled: bool = False
    marked: set[str] = field(default_factory=set)  # kind marks already stamped: one of each per card

    def ornament(self, slot: str, x0: int, x1: int) -> None:
        if self.ornamented or (slot != "header" and MOODS[self.mood]["header"].startswith("band")):
            return  # a banded mood has its band at the top only
        name = MOODS[self.mood][slot]
        piece = SYSTEM_PIECES.get(name)
        if piece is not None and ornament(piece).width <= x1 - x0:
            # The system piece (design system, orn-sys-*), centred in the card's inner width.
            mark = ornament(piece)
            self.c.stamp(mark, x0 + (x1 - x0 - mark.width) // 2, self.c.y)
            h = mark.height
        else:
            draw = ORNAMENTS.get(name)
            if draw is None:
                return
            h = draw(self.c, x0, x1, self.c.y) or 4
        self.c.y += h + (10 if name.startswith("band") else 6)
        self.ornamented = True

    def icon(self, x: int, y: int) -> None:
        name = MOODS[self.mood]["icon"]
        if name in SPRITES:
            stamp_sprite(self.c, x, y, name)


# Moods whose header ornament already is the icon (a heart over the title, a sun over it): no second one at the left.
HEADER_IS_ICON: set[str] = set()


def _title_line(card: Card, x0: int, x1: int, text: str) -> None:
    """A full-width inverted band for moods that ask for one, otherwise the icon at the left with the title centred."""
    label = _label(text)
    c = card.c
    if MOODS[card.mood]["accent"] == "pill":
        pill = next((s for s in (NUMERAL, TITLE, BODY) if text_width(label, s) + 28 <= x1 - x0), BODY)
        h = 7 * pill + 14
        c.round_box(x0, c.y, x1, c.y + h, 6, 2)
        c.fill(x0 + 4, c.y + 4, x1 - 4, c.y + h - 4)
        tx = x0 + (x1 - x0 - text_width(label, pill)) // 2
        c.text(tx, c.y + 7, label, pill)
        _erase_glyphs(c, tx, c.y + 7, label, pill)
        c.y += h + 8
    else:
        icon = card.mood not in HEADER_IS_ICON
        room = x1 - x0 - (30 if icon else 0)
        if icon and text_width(label.split()[0] if label.split() else label, NUMERAL) > room:
            icon, room = False, x1 - x0  # a long word needs the width more than the icon does
        if icon:
            card.icon(x0, c.y)
        scale, lines = title_lines(label, room)
        left = x0 + (30 if icon else 0)
        step = 7 * scale + 6
        for i, line in enumerate(lines):
            c.text(left + (room - text_width(line, scale)) // 2, c.y + i * step, line, scale)
        c.y += len(lines) * step + 2


def _erase_glyphs(c: Canvas, x: int, y: int, text: str, scale: int) -> None:
    """Clears the glyph squares, so the text shows white on a filled pill."""
    for sx, sy, w, h in c.glyph_dots(x, y, text, scale):
        for yy in range(sy, sy + h):
            for xx in range(sx, sx + w):
                if 0 <= xx < 512 and 0 <= yy:
                    c.bits[yy * 64 + (xx >> 3)] &= (~(0x80 >> (xx & 7))) & 0xFF


def title_lines(text: str, max_w: int) -> tuple[int, list[str]]:
    """A title in the dot font, larger than body text. Always the heavy face (scale 6, a multiple of 3, so the
    dots are the same 2 x 2 squares as every other title): one line when it fits, else wrapped at word
    boundaries. Only a single word wider than the line falls back to scale 4."""
    label = str(text)
    if text_width(label, NUMERAL) <= max_w:
        return NUMERAL, [label]
    if all(text_width(word, NUMERAL) <= max_w for word in label.split()):
        lines = wrap_lines(label, NUMERAL, max_w)
        if len(lines) > MAX_TITLE_LINES:  # a title is a label: two lines, the rest is abbreviated, never five lines
            lines = lines[:MAX_TITLE_LINES]
            lines[-1] = lines[-1][: max(1, max_w // (6 * NUMERAL) - 1)].rstrip() + "."
        return NUMERAL, lines
    return TITLE, wrap_lines(label, TITLE, max_w)


MAX_TITLE_LINES = 2
EDGE_GAP = 10  # the least clear space between a line of text and the card border, in dots


def _row(c: Canvas, x0: int, x1: int, label: str, value: str, indent: int = 0) -> int:
    """A label, dot leaders, the value right-aligned: one rhythm for every row. When they do not fit on one line
    a long label wraps on the left, or a long value wraps on the right; the leaders and the right edge stay.
    Returns the row's height."""
    left, right = x0 + indent, x1 - EDGE_GAP
    width = right - left
    lw, vw = solid_width(label, 21), solid_width(value, 21)
    if lw + vw + 22 <= width:
        c.row_solid(left, right, c.y, label, value, 21)
        return ROW
    if lw > vw:  # a long label: it wraps on the left and the value closes the last line
        lines = solid_wrap(label, max(60, width - vw - 22)) or [label]
        for i, line in enumerate(lines[:-1]):
            c.solid(left, c.y + i * ROW, line, 21)
        c.y += (len(lines) - 1) * ROW
        c.row_solid(left, right, c.y, lines[-1], value, 21)
        c.y -= (len(lines) - 1) * ROW
        return len(lines) * ROW
    # a long value: the first line shares the label's row, the rest are right-aligned under it
    lines = solid_wrap(value, max(60, width - lw - 22)) or [value]
    c.row_solid(left, right, c.y, label, lines[0], 21)
    for i, line in enumerate(lines[1:], start=1):
        c.solid(right - solid_width(line, 21), c.y + i * ROW, line, 21)
    return len(lines) * ROW


def _heading(c: Canvas, x: int, text: str, x1: int = OUTER_R) -> None:
    """A title: the dot font at a size larger than body text, centred between x and x1."""
    scale, lines = title_lines(text, x1 - x)
    step = 7 * scale + 6
    for i, line in enumerate(lines):
        c.text(x + (x1 - x - text_width(line, scale)) // 2, c.y + i * step, line, scale)
    c.y += len(lines) * step + 2


# ---- block renderers: draw inside x0..x1 starting at card.c.y, advancing it -----------------
def _greeting(card: Card, s: Mapping[str, Any], x0: int, x1: int) -> None:
    card.ornament("header", x0, x1)
    _heading(card.c, x0, str(s.get("greeting", "")).upper(), x1)
    if s.get("summary"):
        card.c.y += paragraph(card.c, x0, card.c.y, str(s["summary"]), BODY, x1 - x0) + 2
    if s.get("from"):
        card.c.solid(x0, card.c.y, f"- {_label(s['from'])}", 21)  # a greeting is signed like every other note
        card.c.y += ROW


def _metric(card: Card, s: Mapping[str, Any], x0: int, x1: int) -> None:
    c = card.c
    value = str(s.get("value", "--"))
    unit = str(s.get("unit") or "")
    if unit.strip().upper() == str(s.get("label", "")).strip().upper():
        unit = ""  # "750 STEPS" under the label STEPS says it twice
    # The label wraps inside the tile, so a long label never runs over the border.
    scope = {"INSIDE": "IN", "OUTSIDE": "OUT"}.get(str(s.get("scope") or "").strip().upper(), "")
    label = _label(s.get("label", "")) + (f" {scope}" if scope else "")
    for line in wrap_lines(label, BODY, x1 - x0) or [""]:
        c.solid(x0, c.y, line, 21)
        c.y += 7 * BODY + 4
    c.y += 4
    # Numerals are display size (cap 42) when the value and its unit fit the tile, else body size.
    from app.render.canvas import solid_width

    # Numbers are full-line text (Inter): display size (cap 42) when the value fits the tile, else body size.
    cap = int(s.get("_cap") or (42 if solid_width(value, 42) + solid_width(unit, 21) + 6 <= x1 - x0 else 21))
    scale = cap
    c.solid(x0, c.y, value, cap)
    unit_x = x0 + text_width(value, scale) + 6
    # The unit sits beside the value when it fits the tile, otherwise under it, never past the border.
    from app.render.canvas import solid_width

    value_w = solid_width(value, cap)
    unit_x = x0 + value_w + 6
    beside = bool(unit) and unit_x + solid_width(unit, 21) <= x1
    if beside:
        c.solid(unit_x, c.y + cap - 21, unit, 21)  # the unit's baseline sits on the value's baseline  # its baseline sits on the value's baseline
    c.y += cap + 7
    if unit and not beside:
        c.solid(x0, c.y, unit, 21)
        c.y += 7 * BODY + 4
    series = s.get("series")
    if isinstance(series, list) and len(series) > 1:
        c.y += 4
        line_graph(c, x0 + 4, c.y, x1 - 4, c.y + 36, series)
        c.y += 36 + 4
        _time_axis(c, x0, x1, _span(s))
    if s.get("as_of"):
        c.solid(x0, c.y, f"AS OF {str(s['as_of']).upper()}", AXIS_CAP)
        c.y += AXIS_CAP + 8


def _span(s: Mapping[str, Any]) -> str:
    """The time span a chart covers, upper case. A chart with no span says 24H."""
    return str(s.get("range") or "24H").strip().upper()


def _metric_rows(card: Card, s: Mapping[str, Any], x0: int, x1: int) -> None:
    c = card.c
    if s.get("title"):
        _heading(c, x0, _label(s["title"]), x1)
    for r in list(s.get("rows", []))[:12]:
        unit = f" {r['unit']}" if r.get("unit") else ""
        c.y += _row(c, x0, x1, _label(r.get("label", "")), f"{r.get('value', '--')}{unit}")


AXIS_CAP = 14  # chart labels: the smallest full-line size, so they stay quiet under the line


def _time_axis(c: Canvas, x0: int, x1: int, span: str) -> None:
    """Under a chart: the time span it covers on the left and NOW on the right, so the line has a range."""
    c.solid(x0, c.y, span, AXIS_CAP)
    c.solid(x1 - solid_width("NOW", AXIS_CAP), c.y, "NOW", AXIS_CAP)
    c.y += AXIS_CAP + 8


def _graph(card: Card, s: Mapping[str, Any], x0: int, x1: int) -> None:
    c = card.c
    _heading(c, x0, _label(s.get("title", "")), x1)
    series = list(s.get("series", []))
    if len(series) > 1:
        unit = f" {s['unit']}" if s.get("unit") else ""
        # Low and high are labelled above the plot, so the scale reads without a y axis.
        c.solid(x0, c.y, f"HIGH {max(series):.1f}{unit}", AXIS_CAP)
        c.solid(x1 - solid_width(f"LOW {min(series):.1f}{unit}", AXIS_CAP), c.y, f"LOW {min(series):.1f}{unit}", AXIS_CAP)
        mid = f"MID {(max(series) + min(series)) / 2:.1f}{unit}"  # the middle dotted line, so every scale line reads
        left_end = x0 + solid_width(f"HIGH {max(series):.1f}{unit}", AXIS_CAP)
        right_start = x1 - solid_width(f"LOW {min(series):.1f}{unit}", AXIS_CAP)
        if left_end + 12 + solid_width(mid, AXIS_CAP) + 12 <= right_start:
            c.solid((left_end + right_start - solid_width(mid, AXIS_CAP)) // 2, c.y, mid, AXIS_CAP)
        c.y += AXIS_CAP + 6
        plot = max(36, card.plot_h)
        line_graph(c, x0 + 4, c.y, x1 - 4, c.y + plot, series)
        c.y += plot + 6
        _time_axis(c, x0, x1, _span(s))


def _dog_counts(card: Card, s: Mapping[str, Any], x0: int, x1: int) -> None:
    """One entry per dog: the name with leaders to the first column on its first line, and the four counters in
    two left-aligned columns, so the second line sits on the same grid as the first. Nothing is cut."""
    c = card.c
    _heading(c, x0, _label(s.get("title") or "DOGS TODAY"), x1)
    col_b = x1 - EDGE_GAP - 124  # the second column starts here and holds "N POOP" / "N RUN"
    col_a = col_b - 134  # the first column holds "N PEE" / "N FOOD"
    for d in list(s.get("dogs", []))[:2]:
        # Words, not codes: "3 PEE" reads at a glance on the paper, "P3" does not.
        card.icon(x0, c.y)
        name = _label(d.get("name", ""))
        pairs = (
            (f"{d.get('pee', 0)} PEE", f"{d.get('poop', 0)} POOP"),
            (f"{d.get('food', 0)} FOOD", f"{d.get('run', 0)} RUN"),
        )
        c.solid(x0 + 28, c.y, name, 21)
        for xx in range(x0 + 28 + solid_width(name, 21) + 8, col_a - 8, 6):
            c.fill_rect(xx, c.y + 18, 2, 2)  # leaders run from the name to the counters
        for i, (a, b) in enumerate(pairs):
            c.solid(col_a, c.y + i * ROW, a, 21)
            c.solid(col_b, c.y + i * ROW, b, 21)
        c.y += 2 * ROW + 4


def _message(card: Card, s: Mapping[str, Any], x0: int, x1: int) -> None:
    c = card.c
    card.ornament("header", x0, x1)
    clear = _kind_mark(card, "message", x1)
    if s.get("title"):
        _title_line(card, x0, x1 - clear - 4, str(s["title"]))
        clear = 0  # the title line is as tall as the mark, so the body below has the full width
    c.y += paragraph(c, x0, c.y, str(s.get("paragraph", "")), BODY, x1 - x0 - clear) + 6
    if s.get("tip"):
        c.y += paragraph(c, x0, c.y, str(s["tip"]), BODY, x1 - x0) + 4
    card.ornament("divider", x0, x1)
    if s.get("from"):
        c.solid(x0, c.y, f"- {_label(s['from'])}", 21)
        c.y += ROW


def _alert(card: Card, s: Mapping[str, Any], x0: int, x1: int) -> None:
    c = card.c
    card.ornament("header", x0, x1)
    clear = _kind_mark(card, "alert", x1)
    _title_line(card, x0, x1 - clear, str(s.get("label", "")))
    if s.get("paragraph"):
        c.y += paragraph(c, x0, c.y, str(s["paragraph"]), BODY, x1 - x0) + 6
    if s.get("action"):
        c.y += _row(c, x0, x1, "ACTION", _label(s["action"])) + 4
    card.ornament("divider", x0, x1)
    if s.get("from"):
        c.solid(x0, c.y + 4, f"- {_label(s['from'])}", 21)
        c.y += ROW + 4


def _checklist(card: Card, s: Mapping[str, Any], x0: int, x1: int) -> None:
    c = card.c
    card.ornament("header", x0, x1)  # the tone shows on a shopping list as it does on a note
    clear = _kind_mark(card, "checklist", x1)
    if s.get("title"):
        _heading(c, x0, _label(s["title"]), x1 - clear)
        clear = 0
    for item in list(s.get("items", []))[:12]:
        stamp_sprite(c, x0, c.y, "check" if item.get("checked") else "box")
        for line in solid_wrap(_label(item.get("text", "")), x1 - x0 - 26 - EDGE_GAP) or [""]:
            c.solid(x0 + 26, c.y + 2, line, 21)
            c.y += ROW


def _tip(card: Card, s: Mapping[str, Any], x0: int, x1: int) -> None:
    """One line of advice. On its own card it is centred between the tone icon and the kind mark and the card
    centres it vertically; inside a bigger card it leads with its icon like the rest of the text."""
    c = card.c
    icon_is_mark = MOODS[card.mood]["icon"] == KIND_MARKS["tip"]  # a reminder's clock is the kind mark already
    clear = 0 if icon_is_mark else _kind_mark(card, "tip", x1)
    card.icon(x0, c.y)
    if card.in_group:
        c.y += paragraph(c, x0 + 34, c.y, str(s.get("tip", "")), BODY, x1 - x0 - 34 - clear) + 2
    else:
        inner_l, inner_r = x0 + 36, x1 - 36
        for line in solid_wrap(str(s.get("tip", "")), inner_r - inner_l):
            c.solid(inner_l + (inner_r - inner_l - solid_width(line, 21)) // 2, c.y, line, 21)
            c.y += ROW
        c.y += 2
    if s.get("from"):
        c.solid(x0, c.y + 4, f"- {_label(s['from'])}", 21)
        c.y += ROW + 4


def _fact(card: Card, s: Mapping[str, Any], x0: int, x1: int) -> None:
    c = card.c
    card.ornament("header", x0, x1)
    clear = _kind_mark(card, "fact", x1)
    c.y += paragraph(c, x0, c.y, str(s.get("paragraph", "")), BODY, x1 - x0 - clear) + 4
    card.ornament("divider", x0, x1)
    if not card.fact_labeled and not card.in_group:
        card.fact_labeled = True
        c.solid(x0, c.y, "FUN FACT", 21)
        c.y += ROW


RENDERERS: dict[str, Callable[[Card, Mapping[str, Any], int, int], None]] = {
    "greeting": _greeting,
    "metric": _metric,
    "metric_rows": _metric_rows,
    "graph": _graph,
    "dog_counts": _dog_counts,
    "message": _message,
    "alert": _alert,
    "checklist": _checklist,
    "tip": _tip,
    "fact": _fact,
}

# Blocks whose text may be shortened when they run past their max height.
TEXT_FIELDS = {"message": "paragraph", "alert": "paragraph", "fact": "paragraph", "greeting": "summary", "tip": "tip"}


# ---- blocks, layout and strips ----------------------------------------------------------------
@dataclass(frozen=True)
class Block:
    type: str
    slots: Mapping[str, Any]
    mood: str = NEUTRAL
    span: int | None = None  # columns: 1, 2 or 3. None uses the block's default.


@dataclass
class Placed:
    block: Block
    col: int
    span: int
    x0: int
    x1: int
    units: int = 0
    content_h: int = 0
    slots: dict[str, Any] = field(default_factory=dict)


def validate(block: Block) -> None:
    if block.type not in DRAW:
        raise ValueError(f"unknown block type: {block.type}")
    if block.mood not in MOODS:
        raise ValueError(f"unknown mood: {block.mood}")
    lay = LAYOUTS[block.type]
    span = block.span or lay["span"]
    if span not in (1, 2, 3):
        raise ValueError(f"span must be 1, 2 or 3, not {span}")
    if span < lay["min_span"]:
        raise ValueError(f"{block.type} needs at least {lay['min_span']} columns")


def span_x(col: int, span: int, left: int = OUTER_L, right: int = OUTER_R) -> tuple[int, int]:
    cell = (right - left - (COLS - 1) * COL_GAP) // COLS
    x0 = left + col * (cell + COL_GAP)
    return x0, x0 + span * cell + (span - 1) * COL_GAP


def split_strips(blocks: Sequence[Block], max_blocks: int = MAX_BLOCKS) -> list[list[Block]]:
    """Splits an ordered list into strips: at most max_blocks each, and a greeting starts a new strip."""
    strips: list[list[Block]] = []
    cur: list[Block] = []
    for block in blocks:
        validate(block)
    for block in prepare(blocks):  # a headline and what follows it are one card, so one block
        if cur and (len(cur) >= max_blocks or block.type == "greeting" or block.type == "group" or cur[-1].type == "group" or block.slots.get("_cont")):
            strips.append(cur)
            cur = []
        cur.append(block)
    if cur:
        strips.append(cur)
    return strips




def _draw_block(card: Card, block_type: str, slots: Mapping[str, Any], x0: int, x1: int) -> None:
    DRAW[block_type](card, slots, x0, x1)


def _measure(block: Block, slots: Mapping[str, Any], x0: int, x1: int, plot_h: int = 56) -> int:
    """Height the content needs, at the card's width. Measured on a scratch canvas."""
    scratch = Canvas()
    scratch.y = 0
    card = Card(scratch, block.mood, plot_h=plot_h)
    _draw_block(card, block.type, slots, x0 + PAD_H, x1 - PAD_H)
    return scratch.y


def _units_for(content_h: int, lay: dict[str, int]) -> tuple[int, bool]:
    """Whole units for a card whose content is content_h tall. Returns (units, overflowed)."""
    need = math.ceil((content_h + 2 * PAD_V + GAP_V) / UNIT_H)
    units = max(lay["min_units"], need)
    return (lay["max_units"], True) if units > lay["max_units"] else (units, False)


def _shorten(block: Block, slots: dict[str, Any], x0: int, x1: int, max_h: int) -> dict[str, Any]:
    """Cut a text field until the block fits its max height, marking the cut with '...'."""
    field_name = TEXT_FIELDS.get(block.type)
    if not field_name or not slots.get(field_name):
        return slots
    text = str(slots[field_name])
    trimmed = slots
    while text and _measure(block, trimmed, x0, x1) + 2 * PAD_V + GAP_V > max_h * UNIT_H:
        text = text[: max(0, int(len(text) * 0.9))].rstrip()
        trimmed = {**slots, field_name: (text + "...") if text else ""}
    return trimmed


SALUTATIONS = ("HELLO", "HI ", "HEY", "GOOD MORNING", "GOOD EVENING", "GOOD AFTERNOON", "GOOD NIGHT", "DEAR", "PSYCH", "MORNING")
TITLED = ("message", "checklist", "metric_rows", "graph", "dog_counts")


def _is_salutation(text: str) -> bool:
    words = f"{str(text).upper().strip()} "
    return words.startswith(SALUTATIONS) or str(text).upper().strip() in ("HI", "HEY", "HELLO")


def fuse(blocks: Sequence[Block]) -> list[Block]:
    """A headline with no text of its own is the title of the card after it, not a card of its own: one thought,
    one box. A salutation (HELLO LOVE, PSYCH!) is not a title, so it is dropped and the card keeps its own."""
    out: list[Block] = []
    items = list(blocks)
    i = 0
    while i < len(items):
        block = items[i]
        nxt = items[i + 1] if i + 1 < len(items) else None
        if block.type == "greeting" and not block.slots.get("summary") and nxt is not None and nxt.type != "greeting":
            heading = str(block.slots.get("greeting", ""))
            if nxt.type in TITLED or nxt.type == "alert":
                if not _is_salutation(heading):
                    key = "label" if nxt.type == "alert" else "title"
                    nxt = Block(nxt.type, {**nxt.slots, key: heading}, mood=nxt.mood, span=nxt.span)
                items[i + 1] = nxt
                i += 1
                continue
        out.append(block)
        i += 1
    return out


def _group_mood(run: Sequence[Block]) -> str:
    """The card's tone: an alert's if there is one, else the closing note's, else the last block's."""
    for kinds in (("alert",), ("message",)):
        for block in reversed(run):
            if block.type in kinds:
                return block.mood
    return next((b.mood for b in reversed(run) if b.type != "greeting"), run[-1].mood)


def _make_group(run: Sequence[Block]) -> Block:
    parts = list(run)
    last_signed = max((i for i, b in enumerate(parts) if b.type in ("message", "alert", "tip") and b.slots.get("from")), default=-1)
    parts = [  # one signature on a card, the last one
        Block(b.type, {k: v for k, v in b.slots.items() if k != "from"}, mood=b.mood, span=b.span)
        if b.slots.get("from") and i != last_signed
        else b
        for i, b in enumerate(parts)
    ]
    return Block("group", {"parts": parts}, mood=_group_mood(parts), span=COLS)


def _overflows(block: Block) -> bool:
    content = _measure(block, dict(block.slots), OUTER_L, OUTER_R)
    return _units_for(content, LAYOUTS[block.type])[1]


def group(blocks: Sequence[Block]) -> list[Block]:
    """One strip, one card: a headline and the blocks after it are regions of one card, not boxes stacked on
    each other. A new headline, or a card that would be taller than the strip allows, starts the next card."""
    out: list[Block] = []
    run: list[Block] = []

    def flush() -> None:
        if len(run) >= 2:
            out.append(_make_group(run))
        else:
            out.extend(run)
        run.clear()

    for block in blocks:
        if block.type == "group":
            flush()
            out.append(block)
            continue
        if block.type == "greeting" and run:
            flush()
        run.append(block)
        if len(run) >= 2 and _overflows(_make_group(run)):
            last = run.pop()
            flush()
            run.append(last)
    flush()
    return out


def _group(card: Card, s: Mapping[str, Any], x0: int, x1: int) -> None:
    """Draws every part in one card: headline, nested metric tiles, then the other blocks, 8 dots apart."""
    c = card.c
    card.in_group = True
    parts: list[Block] = list(s["parts"])
    i = 0
    first = True
    while i < len(parts):
        part = parts[i]
        if not first:
            c.y += 8
        if part.type == "metric":
            j = i
            while j < len(parts) and parts[j].type == "metric":
                j += 1
            if first:
                card.ornament("header", x0, x1)
            rows, _ = layout(parts[i:j], x0, x1, grouped=True)
            for row in rows:
                _draw_row(c, row)
            i = j
        else:
            DRAW[part.type](card, part.slots, x0, x1)
            i += 1
        first = False


LAYOUTS = {**LAYOUT, "group": {"span": 3, "min_span": 3, "min_units": 2, "max_units": 18}}
DRAW = {**RENDERERS, "group": _group}  # RENDERERS is the catalogue; a group is made by the layout, never sent


SPILL = {"message": "paragraph", "alert": "paragraph", "fact": "paragraph"}


def spill(blocks: Sequence[Block]) -> list[Block]:
    """Text that is too long for one card continues on the next one, split between sentences: nothing is cut. The
    continuation is titled CONT. and only the last card carries the signature and the action."""
    out: list[Block] = []
    for block in blocks:
        key = SPILL.get(block.type)
        if key is None or not block.slots.get(key) or not _overflows(block):
            out.append(block)
            continue
        paras = [p for p in re.split(r"\n\s*\n", str(block.slots[key])) if p.strip()]
        units: list[tuple[str, str]] = []  # (text, separator before it)
        for pi, para in enumerate(paras):
            for si, sentence in enumerate(re.split(r"(?<=[.!?])\s+", para.strip())):
                for wi, chunk in enumerate(_hard_words(sentence)):
                    units.append((chunk, "\n\n" if pi and not si and not wi else " "))
        head_key = "label" if block.type == "alert" else "title"
        tail_keys = ("from", "action", "tip")

        def piece(text: str, first: bool, last: bool) -> Block:
            slots = {k: v for k, v in block.slots.items() if last or k not in tail_keys}
            slots[key] = text
            if not first:
                base = str(block.slots.get(head_key) or "")
                slots[head_key] = _cont_title(base)
                slots["_cont"] = True
            return Block(block.type, slots, mood=block.mood, span=block.span)

        text, pieces = "", []
        for chunk, sep in units:
            trial = f"{text}{sep}{chunk}" if text else chunk
            if text and _overflows(piece(trial, not pieces, True)):  # fit with the signature, so the last card never overflows
                pieces.append(text)
                text = chunk
            else:
                text = trial
        pieces.append(text)
        out.extend(piece(t, i == 0, i == len(pieces) - 1) for i, t in enumerate(pieces))
    return out


def _cont_title(base: str) -> str:
    """The original title with CONT. after it, with words dropped from the title until it fits two lines."""
    words = base.upper().split()
    while words:
        text = " ".join(words) + " CONT."
        scale, lines = title_lines(text, 380)
        if scale == NUMERAL and len(lines) <= MAX_TITLE_LINES and not lines[-1].endswith("."):
            return text
        if scale == NUMERAL and len(lines) <= MAX_TITLE_LINES and text_width(lines[-1], NUMERAL) <= 380 and " ".join(lines) == text:
            return text
        words.pop()
    return "CONT."


def _hard_words(sentence: str, longest: int = 400) -> list[str]:
    """A sentence longer than a card is cut between words, so it can still be placed."""
    words, chunks, cur = sentence.split(), [], ""
    for word in words:
        if cur and len(cur) + 1 + len(word) > longest:
            chunks.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}" if cur else word
    return chunks + [cur] if cur else chunks


def prepare(blocks: Sequence[Block]) -> list[Block]:
    """What the printer draws from what was sent: headlines fused into titles, long text continued on the next
    card, and blocks gathered into one card per strip."""
    return group(spill(fuse(blocks)))


def _place(block: Block, slots: dict[str, Any], x0: int, x1: int, col: int = 0, span: int = COLS) -> Placed:
    content = _measure(block, slots, x0, x1)
    units, _ = _units_for(content, LAYOUTS[block.type])
    return Placed(block, col, span, x0, x1, units, content, slots)


def _equalise(row: list[Placed], left: int = OUTER_L, right: int = OUTER_R) -> list[Placed]:
    """A row that does not fill the page is split evenly across it, so no row has a gap. Metric tiles in one row
    share one numeral size, so their numbers, charts and axes line up."""
    used = sum(p.span for p in row)
    if used < COLS:
        n = len(row)
        width = (right - left - (n - 1) * COL_GAP) // n
        placed = []
        for k, p in enumerate(row):
            x0 = left + k * (width + COL_GAP)
            x1 = right if k == n - 1 else x0 + width
            placed.append(_place(p.block, dict(p.slots), x0, x1, p.col, p.span))
        row = placed
    metrics = [p for p in row if p.block.type == "metric"]
    if len(metrics) > 1:
        from app.render.canvas import solid_width

        fits = all(
            solid_width(str(p.slots.get("value", "--")), 42) + solid_width(str(p.slots.get("unit") or ""), 21) + 6 <= p.x1 - p.x0 - 2 * PAD_H
            for p in metrics
        )
        cap = 42 if fits else 21
        row = [_place(p.block, {**p.slots, "_cap": cap}, p.x0, p.x1, p.col, p.span) if p in metrics else p for p in row]
    return row


def layout(blocks: Sequence[Block], left: int = OUTER_L, right: int = OUTER_R, grouped: bool = False) -> tuple[list[list[Placed]], list[str]]:
    """Places blocks in rows, sizes each card in whole units, and reports any cut-off text."""
    rows: list[list[Placed]] = []
    notes: list[str] = []
    row: list[Placed] = []
    used = 0
    for block in (list(blocks) if grouped else fuse(blocks)):
        validate(block)
        lay = LAYOUTS[block.type]
        span = block.span or lay["span"]
        if used + span > COLS:
            rows.append(row)
            row, used = [], 0
        x0, x1 = span_x(used, span, left, right)
        slots = dict(block.slots)
        content = _measure(block, slots, x0, x1)
        units, overflow = _units_for(content, lay)
        if overflow:
            slots = _shorten(block, slots, x0, x1, lay["max_units"])
            notes.append(f"{block.type} shortened to fit {lay['max_units']} units")
            content = _measure(block, slots, x0, x1)
            units, _ = _units_for(content, lay)
        row.append(Placed(block, used, span, x0, x1, units, content, slots))
        used += span
    if row:
        rows.append(row)
    rows = [_equalise(row, left, right) for row in rows]
    return rows, notes


def _draw_row(c: Canvas, row: list[Placed]) -> None:
    row_units = max(p.units for p in row)
    top = c.y
    height = row_units * UNIT_H - GAP_V
    for p in row:
        # A graph takes the spare height of its card: the card height less padding, heading and footer.
        card = Card(c, p.block.mood, plot_h=GRAPH_PLOT)
        c.y = top + PAD_V
        if p.block.type == "tip" or (p.block.type == "greeting" and not p.slots.get("summary")):
            c.y = top + max(PAD_V, (height - p.content_h) // 2)  # one line or one title: centred in its card
        _draw_block(card, p.block.type, p.slots, p.x0 + PAD_H, p.x1 - PAD_H)
        mood = p.block.mood
        c.round_box(p.x0, top, p.x1, top + height, RADIUS_BY_MOOD.get(mood, RADIUS), STROKE_BY_MOOD.get(mood, STROKE))
    c.y = top + row_units * UNIT_H


def render_strip(
    blocks: Sequence[Block],
    *,
    margin_top: int = MARGIN_TOP,
    margin_bottom: int = MARGIN_BOTTOM,
) -> Bitmap:
    """Draws one strip with margins. Raises ValueError for an unknown type, mood or span, or too many blocks."""
    bitmap, _ = render_strip_with_notes(blocks, margin_top=margin_top, margin_bottom=margin_bottom)
    return bitmap


def render_strip_with_notes(
    blocks: Sequence[Block],
    *,
    margin_top: int = MARGIN_TOP,
    margin_bottom: int = MARGIN_BOTTOM,
) -> tuple[Bitmap, list[str]]:
    if not blocks:
        raise ValueError("a strip needs at least one block")
    if len(blocks) > MAX_BLOCKS:
        raise ValueError(f"a strip holds at most {MAX_BLOCKS} blocks")
    rows, notes = layout(prepare(blocks))
    c = Canvas()
    c.y = margin_top
    for row in rows:
        _draw_row(c, row)
    c.y -= GAP_V  # the gap after the last row is not part of the strip: the bottom margin replaces it
    c.y += margin_bottom
    return c.crop(0), notes
