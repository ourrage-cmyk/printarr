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

# Layout per block type: span in columns and height in units. Text is fluid; metric tiles are fluid up to 3.
LAYOUT: dict[str, dict[str, int]] = {
    "greeting": {"span": 3, "min_span": 3, "min_units": 1, "max_units": 6},
    "metric": {"span": 1, "min_span": 1, "min_units": 2, "max_units": 4},
    "metric_rows": {"span": 3, "min_span": 2, "min_units": 2, "max_units": 8},
    "graph": {"span": 3, "min_span": 2, "min_units": 3, "max_units": 8},
    "dog_counts": {"span": 3, "min_span": 2, "min_units": 2, "max_units": 5},
    "message": {"span": 3, "min_span": 2, "min_units": 2, "max_units": 16},
    "alert": {"span": 3, "min_span": 2, "min_units": 2, "max_units": 6},
    "checklist": {"span": 3, "min_span": 2, "min_units": 2, "max_units": 10},
    "tip": {"span": 3, "min_span": 2, "min_units": 1, "max_units": 4},
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
}


def stamp_sprite(c: Canvas, x: int, y: int, name: str, scale: int = 3) -> None:
    for r, row in enumerate(SPRITES[name]):
        for col, ch in enumerate(row):
            if ch == "#":
                c.fill_rect(x + col * scale, y + r * scale, scale, scale)


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


def paragraph(c: Canvas, x: int, y: int, text: str, scale: int, max_w: int) -> int:
    lines = wrap_lines(text, scale, max_w)
    for i, line in enumerate(lines):
        if scale == BODY:
            c.solid(x, y + i * (7 * scale + 4), line, 21)  # body text is full-line (Inter), not dot matrix
        else:
            c.text(x, y + i * (7 * scale + 4), line, scale)
    return len(lines) * (7 * scale + 4)


def paragraph_height(text: str, scale: int, max_w: int) -> int:
    return len(wrap_lines(text, scale, max_w)) * (7 * scale + 4)


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
    """A pill for moods that ask for one, otherwise the icon with the label."""
    label = _label(text)
    c = card.c
    if MOODS[card.mood]["accent"] == "pill":
        w = min(text_width(label, BODY) + 28, x1 - x0)
        h = 7 * BODY + 14
        c.round_box(x0, c.y, x0 + w, c.y + h, h // 2, 2)
        c.fill(x0 + 4, c.y + 4, x0 + w - 4, c.y + h - 4)
        c.text(x0 + 14, c.y + 7, label, BODY)
        _erase_glyphs(c, x0 + 14, c.y + 7, label, BODY)
        c.y += h + 8
    else:
        card.icon(x0, c.y)
        c.text(x0 + 36, c.y + 2, label, BODY)
        c.y += 7 * BODY + 9


def _erase_glyphs(c: Canvas, x: int, y: int, text: str, scale: int) -> None:
    """Clears the glyph squares, so the text shows white on a filled pill."""
    for sx, sy, w, h in c.glyph_dots(x, y, text, scale):
        for yy in range(sy, sy + h):
            for xx in range(sx, sx + w):
                if 0 <= xx < 512 and 0 <= yy:
                    c.bits[yy * 64 + (xx >> 3)] &= (~(0x80 >> (xx & 7))) & 0xFF


def _heading(c: Canvas, x: int, text: str, scale: int = BODY) -> None:
    c.text(x, c.y, text, scale)  # a title: dot matrix
    c.y += 7 * scale + 8


# ---- block renderers: draw inside x0..x1 starting at card.c.y, advancing it -----------------
def _greeting(card: Card, s: Mapping[str, Any], x0: int, x1: int) -> None:
    card.ornament("header", x0, x1)
    card.c.text(x0, card.c.y, str(s.get("greeting", "")).upper(), 3)
    card.c.y += 21 + 8
    if s.get("summary"):
        card.c.y += paragraph(card.c, x0, card.c.y, str(s["summary"]), BODY, x1 - x0) + 2


def _metric(card: Card, s: Mapping[str, Any], x0: int, x1: int) -> None:
    c = card.c
    value = str(s.get("value", "--"))
    unit = str(s.get("unit") or "")
    if unit.strip().upper() == str(s.get("label", "")).strip().upper():
        unit = ""  # "750 STEPS" under the label STEPS says it twice
    # The label wraps inside the tile, so a long label never runs over the border.
    for line in wrap_lines(_label(s.get("label", "")), BODY, x1 - x0) or [""]:
        c.solid(x0, c.y, line, 21)
        c.y += 7 * BODY + 4
    c.y += 4
    # Numerals are display size (cap 42) when the value and its unit fit the tile, else body size.
    from app.render.canvas import solid_width

    # Numbers are full-line text (Inter): display size (cap 42) when the value fits the tile, else body size.
    cap = 42 if solid_width(value, 42) + solid_width(unit, 21) + 6 <= x1 - x0 else 21
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


def _span(s: Mapping[str, Any]) -> str:
    """The time span a chart covers, upper case. A chart with no span says 24H."""
    return str(s.get("range") or "24H").strip().upper()


def _metric_rows(card: Card, s: Mapping[str, Any], x0: int, x1: int) -> None:
    c = card.c
    if s.get("title"):
        _heading(c, x0, _label(s["title"]))
    for r in list(s.get("rows", []))[:12]:
        card.icon(x0, c.y)
        unit = f" {r['unit']}" if r.get("unit") else ""
        c.row_solid(x0 + 28, x1, c.y + 2, _label(r.get("label", "")), f"{r.get('value', '--')}{unit}", 21)
        c.y += ROW


AXIS_CAP = 14  # chart labels: the smallest full-line size, so they stay quiet under the line


def _time_axis(c: Canvas, x0: int, x1: int, span: str) -> None:
    """Under a chart: the time span it covers on the left and NOW on the right, so the line has a range."""
    c.solid(x0, c.y, span, AXIS_CAP)
    c.solid(x1 - solid_width("NOW", AXIS_CAP), c.y, "NOW", AXIS_CAP)
    c.y += AXIS_CAP + 8


def _graph(card: Card, s: Mapping[str, Any], x0: int, x1: int) -> None:
    c = card.c
    _heading(c, x0, _label(s.get("title", "")))
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
    c = card.c
    _heading(c, x0, "DOGS TODAY")
    for d in list(s.get("dogs", []))[:2]:
        # Words, not codes: "3 PEE" reads at a glance on the paper, "P3" does not.
        card.icon(x0, c.y)
        c.row_solid(x0 + 28, x1 - 10, c.y + 2, _label(d.get("name", "")), f"{d.get('pee', 0)} PEE, {d.get('poop', 0)} POOP", 21)
        c.y += ROW
        c.solid(x0 + 28, c.y + 2, f"{d.get('food', 0)} FOOD, {d.get('run', 0)} RUN", 21)
        c.y += ROW


def _message(card: Card, s: Mapping[str, Any], x0: int, x1: int) -> None:
    c = card.c
    card.ornament("header", x0, x1)
    if s.get("title"):
        _title_line(card, x0, x1, str(s["title"]))
    c.y += paragraph(c, x0, c.y, str(s.get("paragraph", "")), BODY, x1 - x0) + 6
    if s.get("tip"):
        c.y += paragraph(c, x0, c.y, str(s["tip"]), BODY, x1 - x0) + 4
    card.ornament("divider", x0, x1)
    if s.get("from"):
        c.solid(x0, c.y, f"- {_label(s['from'])}", 21)
        c.y += ROW


def _alert(card: Card, s: Mapping[str, Any], x0: int, x1: int) -> None:
    c = card.c
    card.ornament("header", x0, x1)
    _title_line(card, x0, x1, str(s.get("label", "")))
    if s.get("paragraph"):
        c.y += paragraph(c, x0, c.y, str(s["paragraph"]), BODY, x1 - x0) + 6
    if s.get("action"):
        c.row_solid(x0, x1, c.y, "ACTION", _label(s["action"]), 21)
        c.y += ROW
    card.ornament("divider", x0, x1)


def _checklist(card: Card, s: Mapping[str, Any], x0: int, x1: int) -> None:
    c = card.c
    if s.get("title"):
        _heading(c, x0, _label(s["title"]), NUMERAL if len(_label(s["title"])) * 6 * NUMERAL <= x1 - x0 else BODY)
    for item in list(s.get("items", []))[:12]:
        stamp_sprite(c, x0, c.y, "check" if item.get("checked") else "box")
        c.solid(x0 + 26, c.y + 2, _label(item.get("text", "")), 21)
        c.y += ROW


def _tip(card: Card, s: Mapping[str, Any], x0: int, x1: int) -> None:
    card.icon(x0, card.c.y)
    card.c.y += paragraph(card.c, x0 + 28, card.c.y, str(s.get("tip", "")), BODY, x1 - x0 - 28) + 2


def _fact(card: Card, s: Mapping[str, Any], x0: int, x1: int) -> None:
    c = card.c
    card.ornament("header", x0, x1)
    c.y += paragraph(c, x0, c.y, str(s.get("paragraph", "")), BODY, x1 - x0) + 4
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
    if block.type not in RENDERERS:
        raise ValueError(f"unknown block type: {block.type}")
    if block.mood not in MOODS:
        raise ValueError(f"unknown mood: {block.mood}")
    lay = LAYOUT[block.type]
    span = block.span or lay["span"]
    if span not in (1, 2, 3):
        raise ValueError(f"span must be 1, 2 or 3, not {span}")
    if span < lay["min_span"]:
        raise ValueError(f"{block.type} needs at least {lay['min_span']} columns")


def span_x(col: int, span: int) -> tuple[int, int]:
    x0 = OUTER_L + col * (CELL_W + COL_GAP)
    return x0, x0 + span * CELL_W + (span - 1) * COL_GAP


def split_strips(blocks: Sequence[Block], max_blocks: int = MAX_BLOCKS) -> list[list[Block]]:
    """Splits an ordered list into strips: at most max_blocks each, and a greeting starts a new strip."""
    strips: list[list[Block]] = []
    cur: list[Block] = []
    for block in blocks:
        validate(block)
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
    RENDERERS[block.type](card, slots, x0 + PAD_H, x1 - PAD_H)
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


def _pack(row: list[Placed]) -> list[Placed]:
    """A row with an empty column gives its last card the spare columns, so no row has a gap."""
    used = sum(p.span for p in row)
    if len(row) < 2 or used >= COLS:
        return row
    last = row[-1]
    if last.block.span is not None:
        return row
    widened = Block(last.block.type, last.block.slots, mood=last.block.mood, span=last.span + (COLS - used))
    lay = LAYOUT[widened.type]
    x0, x1 = span_x(last.col, widened.span or lay["span"])
    slots = dict(widened.slots)
    content = _measure(widened, slots, x0, x1)
    units, _ = _units_for(content, lay)
    return row[:-1] + [Placed(widened, last.col, widened.span, x0, x1, units, content, slots)]


def _widen_lone(row: list[Placed]) -> list[Placed]:
    """A row of one card that is narrower than the page takes the full width, so it is centred on the paper."""
    if len(row) != 1 or row[0].span >= COLS or row[0].block.span is not None:
        return row
    block = row[0].block
    lay = LAYOUT[block.type]
    x0, x1 = span_x(0, COLS)
    slots = dict(block.slots)
    content = _measure(block, slots, x0, x1)
    units, _ = _units_for(content, lay)
    return [Placed(block, 0, COLS, x0, x1, units, content, slots)]


def layout(blocks: Sequence[Block]) -> tuple[list[list[Placed]], list[str]]:
    """Places blocks in rows, sizes each card in whole units, and reports any cut-off text."""
    rows: list[list[Placed]] = []
    notes: list[str] = []
    row: list[Placed] = []
    used = 0
    for block in blocks:
        validate(block)
        lay = LAYOUT[block.type]
        span = block.span or lay["span"]
        if used + span > COLS:
            rows.append(row)
            row, used = [], 0
        x0, x1 = span_x(used, span)
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
    rows = [_widen_lone(row) for row in rows]
    rows = [_pack(row) for row in rows]
    return rows, notes


def _draw_row(c: Canvas, row: list[Placed]) -> None:
    row_units = max(p.units for p in row)
    top = c.y
    height = row_units * UNIT_H - GAP_V
    for p in row:
        # A graph takes the spare height of its card: the card height less padding, heading and footer.
        card = Card(c, p.block.mood, plot_h=max(36, height - 2 * PAD_V - 80))
        c.y = top + PAD_V
        RENDERERS[p.block.type](card, p.slots, p.x0 + PAD_H, p.x1 - PAD_H)
        c.round_box(p.x0, top, p.x1, top + height, RADIUS, STROKE)
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
