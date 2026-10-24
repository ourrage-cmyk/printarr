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
STROKE_BY_MOOD: dict[str, int] = {"urgent": 4, "critical": 5, "upset": 4, "firm_complaint": 4}
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
    "check": ("....#", "...##", "#.##.", "##.#.", ".##..", "..#.."),
    "star": ("....#....", "....#....", "#########", ".#######.", "..#####..", ".##.#.##.", "##.....##", ".........", "........."),
    "warn": ("....#....", "...###...", "...###...", "..##.##..", "..##.##..", ".##...##.", ".##...##.", "#########", "........."),
    "question": (".###.", "#...#", "....#", "...#.", "..#..", ".....", "..#.."),
    # kind marks: one per kind of ticket, stamped at the card's top-right corner
    "cart": ("##.......", ".#.......", ".#######.", ".#.#.#.#.", "..#####..", "..#...#..", "..##.##.."),
    "clock": ("..#####..", ".#.....#.", "#...#...#", "#...#...#", "#...###.#", "#.......#", ".#.....#.", "..#####.."),
    "bulb": ("..###..", ".#...#.", "#.....#", "#.....#", ".#...#.", "..###..", "..###..", "..###.."),
    "envelope": ("#########", "##.....##", "#.#...#.#", "#..###..#", "#.......#", "#########"),
}

# The mark each block type wears, so a note, an alert, a reminder, a fun fact and a shopping list
# are told apart at a glance by something other than their words. Tones change the header and the
# icon; the kind mark is separate and sits at the top-right.
KIND_MARKS: dict[str, str] = {"message": "envelope", "alert": "bolt", "checklist": "cart", "tip": "clock", "fact": "bulb"}


def stamp_sprite(c: Canvas, x: int, y: int, name: str, scale: int = 3) -> None:
    for r, row in enumerate(SPRITES[name]):
        for col, ch in enumerate(row):
            if ch == "#":
                c.fill_rect(x + col * scale, y + r * scale, scale, scale)


def _kind_mark(card: "Card", kind: str, x1: int) -> int:
    """Stamps the kind mark at the card's top-right corner. Returns the width the text beside it must leave."""
    name = KIND_MARKS.get(kind)
    if name is None:
        return 0
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


ORNAMENTS: dict[str, Callable[[Canvas, int, int, int], int]] = {
    "sunStrip": _sun_strip,
    "dottedWave": _dotted_wave,
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

    def ornament(self, slot: str, x0: int, x1: int) -> None:
        if self.ornamented:
            return
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
        self.c.y += h + 6
        self.ornamented = True

    def icon(self, x: int, y: int) -> None:
        name = MOODS[self.mood]["icon"]
        if name in SPRITES:
            stamp_sprite(self.c, x, y, name)


def _title_line(card: Card, x0: int, x1: int, text: str) -> None:
    """A pill for moods that ask for one, otherwise the icon at the left with the title centred."""
    label = _label(text)
    c = card.c
    if MOODS[card.mood]["accent"] == "pill":
        # The pill label is one line at the largest title size that fits beside its padding.
        pill = next((s for s in (NUMERAL, TITLE, BODY) if text_width(label, s) + 28 <= x1 - x0), BODY)
        w = min(text_width(label, pill) + 28, x1 - x0)
        h = 7 * pill + 14
        left = x0 + (x1 - x0 - w) // 2
        c.round_box(left, c.y, left + w, c.y + h, h // 2, 2)
        c.fill(left + 4, c.y + 4, left + w - 4, c.y + h - 4)
        c.text(left + 14, c.y + 7, label, pill)
        _erase_glyphs(c, left + 14, c.y + 7, label, pill)
        c.y += h + 8
    else:
        card.icon(x0, c.y)
        scale, lines = title_lines(label, x1 - x0 - 30)
        step = 7 * scale + 6
        for i, line in enumerate(lines):
            c.text(x0 + 30 + (x1 - x0 - 30 - text_width(line, scale)) // 2, c.y + i * step, line, scale)
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
        return NUMERAL, wrap_lines(label, NUMERAL, max_w)
    return TITLE, wrap_lines(label, TITLE, max_w)


EDGE_GAP = 10  # the least clear space between a line of text and the card border, in dots


def _row(c: Canvas, x0: int, x1: int, label: str, value: str, indent: int = 0) -> int:
    """A label with its value at the right: on one line when the two fit with an edge gap and some leaders,
    else the value goes under the label, left aligned and wrapped, so nothing runs into the border.
    Returns its height."""
    from app.render.canvas import solid_width

    width = x1 - EDGE_GAP - (x0 + indent)
    if solid_width(label, 21) + solid_width(value, 21) + 8 + 24 <= width:
        c.row_solid(x0 + indent, x1 - EDGE_GAP, c.y, label, value, 21)
        return ROW
    c.solid(x0 + indent, c.y, label, 21)
    lines = solid_wrap(value, width)
    for i, line in enumerate(lines):
        c.solid(x0 + indent, c.y + (i + 1) * ROW, line, 21)
    return (1 + len(lines)) * ROW


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


def _metric(card: Card, s: Mapping[str, Any], x0: int, x1: int) -> None:
    c = card.c
    value = str(s.get("value", "--"))
    unit = str(s.get("unit") or "")
    if unit.strip().upper() == str(s.get("label", "")).strip().upper():
        unit = ""  # "750 STEPS" under the label STEPS says it twice
    # The label wraps inside the tile, so a long label never runs over the border.
    scope = str(s.get("scope") or "").strip().upper()
    label = _label(s.get("label", "")) + (f" {scope}" if scope in ("IN", "OUT") else "")
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
        card.icon(x0, c.y)
        unit = f" {r['unit']}" if r.get("unit") else ""
        c.y += _row(c, x0, x1, _label(r.get("label", "")), f"{r.get('value', '--')}{unit}", indent=28)


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
        c.y += AXIS_CAP + 6
        plot = max(36, card.plot_h)
        line_graph(c, x0 + 4, c.y, x1 - 4, c.y + plot, series)
        c.y += plot + 6
        _time_axis(c, x0, x1, _span(s))


def _dog_counts(card: Card, s: Mapping[str, Any], x0: int, x1: int) -> None:
    """One entry per dog: the name with leaders to the first two counters, the other two on the line under,
    the counters in two right-aligned columns so they read as a table. Nothing is cut."""
    c = card.c
    _heading(c, x0, _label(s.get("title") or "DOGS TODAY"), x1)
    right = x1 - EDGE_GAP
    col_b = right
    col_a = right - 118  # the second column is the wider "N POOP"/"N FOOD"/"N RUN" and ends at the edge gap
    for d in list(s.get("dogs", []))[:2]:
        # Words, not codes: "3 PEE" reads at a glance on the paper, "P3" does not.
        card.icon(x0, c.y)
        name = _label(d.get("name", ""))
        pairs = (
            (f"{d.get('pee', 0)} PEE", f"{d.get('poop', 0)} POOP"),
            (f"{d.get('food', 0)} FOOD", f"{d.get('run', 0)} RUN"),
        )
        for i, (a, b) in enumerate(pairs):
            y = c.y + i * ROW
            left = x0 + 28
            if i == 0:
                c.solid(left, y, name, 21)
                left += solid_width(name, 21)
            wa, wb = solid_width(a, 21), solid_width(b, 21)
            for xx in range(left + 8, col_a - wa - 8, 6):
                c.fill_rect(xx, y + 18, 2, 2)  # leaders on both lines
            c.solid(col_a - wa, y, a, 21)
            c.solid(col_b - wb, y, b, 21)
        c.y += 2 * ROW + 4


def _message(card: Card, s: Mapping[str, Any], x0: int, x1: int) -> None:
    c = card.c
    card.ornament("header", x0, x1)
    clear = _kind_mark(card, "message", x1)
    if s.get("title"):
        _title_line(card, x0, x1 - clear + 5, str(s["title"]))
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
    _title_line(card, x0, x1 - clear + 5, str(s.get("label", "")))
    if s.get("paragraph"):
        c.y += paragraph(c, x0, c.y, str(s["paragraph"]), BODY, x1 - x0) + 6
    if s.get("action"):
        c.y += _row(c, x0, x1, "ACTION", _label(s["action"]))
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
    """One line of advice, centred between the tone icon and the kind mark; the card centres it vertically."""
    c = card.c
    _kind_mark(card, "tip", x1)
    card.icon(x0, c.y)
    inner_l, inner_r = x0 + 36, x1 - 36
    lines = solid_wrap(str(s.get("tip", "")), inner_r - inner_l)
    for line in lines:
        c.solid(inner_l + (inner_r - inner_l - solid_width(line, 21)) // 2, c.y, line, 21)
        c.y += ROW
    c.y += 2


def _fact(card: Card, s: Mapping[str, Any], x0: int, x1: int) -> None:
    c = card.c
    card.ornament("header", x0, x1)
    clear = _kind_mark(card, "fact", x1)
    c.y += paragraph(c, x0, c.y, str(s.get("paragraph", "")), BODY, x1 - x0 - clear) + 4
    card.ornament("divider", x0, x1)
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
    for block in group(fuse(blocks)):  # a headline, its tiles and the closing line are one card, so one block
        if cur and (len(cur) >= max_blocks or block.type == "greeting"):
            strips.append(cur)
            cur = []
        cur.append(block)
    if cur:
        strips.append(cur)
    return strips


def _measure(block: Block, slots: Mapping[str, Any], x0: int, x1: int, plot_h: int = 56) -> int:
    """Height the content needs, at the card's width. Measured on a scratch canvas."""
    scratch = Canvas()
    scratch.y = 0
    card = Card(scratch, block.mood, plot_h=plot_h)
    DRAW[block.type](card, slots, x0 + PAD_H, x1 - PAD_H)
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


GROUP_TAILS = ("tip", "message")


def group(blocks: Sequence[Block]) -> list[Block]:
    """Metric tiles are content of the card that follows them, not siblings above it: a headline (if any), the
    tiles and the closing tip or note become one card with the tiles nested inside."""
    out: list[Block] = []
    items = list(blocks)
    i = 0
    while i < len(items):
        start = i
        head = items[i] if items[i].type == "greeting" else None
        j = i + 1 if head else i
        metrics: list[Block] = []
        while j < len(items) and items[j].type == "metric":
            metrics.append(items[j])
            j += 1
        if metrics and j < len(items) and items[j].type in GROUP_TAILS:
            tail = items[j]
            out.append(Block("group", {"head": head, "metrics": metrics, "tail": tail}, mood=tail.mood, span=COLS))
            i = j + 1
        else:
            out.append(items[start])
            i = start + 1
    return out


def _group(card: Card, s: Mapping[str, Any], x0: int, x1: int) -> None:
    """Draws the headline, the nested tiles and the closing line inside one card."""
    c = card.c
    head, tail = s.get("head"), s["tail"]
    if head is not None:
        _greeting(card, head.slots, x0, x1)
        c.y += 4
    else:
        card.ornament("header", x0, x1)
    rows, _ = layout(s["metrics"], x0, x1, grouped=True)
    for row in rows:
        _draw_row(c, row)
    DRAW[tail.type](card, tail.slots, x0, x1)


LAYOUTS = {**LAYOUT, "group": {"span": 3, "min_span": 3, "min_units": 2, "max_units": 18}}
DRAW = {**RENDERERS, "group": _group}  # RENDERERS is the catalogue; a group is made by the layout, never sent


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
    for block in (list(blocks) if grouped else group(fuse(blocks))):
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
        DRAW[p.block.type](card, p.slots, p.x0 + PAD_H, p.x1 - PAD_H)
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
    rows, notes = layout(blocks)
    c = Canvas()
    c.y = margin_top
    for row in rows:
        _draw_row(c, row)
    c.y -= GAP_V  # the gap after the last row is not part of the strip: the bottom margin replaces it
    c.y += margin_bottom
    return c.crop(0), notes
