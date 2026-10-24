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

from app.render.canvas import Bitmap, Canvas, js_round, text_width

CATALOGUE: dict[str, Any] = json.loads((Path(__file__).parent / "system" / "blocks.json").read_text())
SHELL: dict[str, Any] = CATALOGUE["shell"]
GRID: dict[str, int] = CATALOGUE["grid"]
MOODS: dict[str, dict[str, str]] = CATALOGUE["moods"]
BLOCKS: dict[str, dict[str, Any]] = CATALOGUE["blocks"]

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
    "dog_counts": {"span": 3, "min_span": 2, "min_units": 2, "max_units": 4},
    "message": {"span": 3, "min_span": 2, "min_units": 2, "max_units": 16},
    "alert": {"span": 3, "min_span": 2, "min_units": 2, "max_units": 6},
    "checklist": {"span": 3, "min_span": 2, "min_units": 2, "max_units": 10},
    "tip": {"span": 3, "min_span": 2, "min_units": 1, "max_units": 2},
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
    "check": (".....#", "....##", "#..##.", "##.#..", ".##...", "..#..."),
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
    for a in range(180, 361, 4):
        rad = math.radians(a)
        c.fill_rect(js_round(cx + math.cos(rad) * 16) - 1, js_round(y + 16 + math.sin(rad) * 16) - 1, 3, 3)
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


# ---- text helpers --------------------------------------------------------------------------------
def _label(text: object) -> str:
    """Upper case, with underscores as spaces: the dot font has no underscore."""
    return str(text).upper().replace("_", " ")


def wrap_lines(text: str, scale: int, max_w: int) -> list[str]:
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
        draw = ORNAMENTS.get(MOODS[self.mood][slot])
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
        w = min(text_width(label, 2) + 28, x1 - x0)
        h = 7 * 2 + 14
        c.round_box(x0, c.y, x0 + w, c.y + h, h // 2, 2)
        c.fill(x0 + 4, c.y + 4, x0 + w - 4, c.y + h - 4)
        c.text(x0 + 14, c.y + 7, label, 2)
        _erase_glyphs(c, x0 + 14, c.y + 7, label, 2)
        c.y += h + 8
    else:
        card.icon(x0, c.y)
        c.text(x0 + 36, c.y + 2, label, 2)
        c.y += 30


def _erase_glyphs(c: Canvas, x: int, y: int, text: str, scale: int) -> None:
    """Clears glyph dots, so the text shows white on a filled pill."""
    from app.render.glyphs import GLYPHS

    cx = x
    for ch in text:
        glyph = GLYPHS.get(ch.upper(), GLYPHS["?"])
        for r in range(7):
            for col in range(5):
                if glyph[r][col] != "#":
                    continue
                for yy in range(scale):
                    for xx in range(scale):
                        px = cx + col * scale + xx
                        py = y + r * scale + yy
                        if 0 <= px < 512 and 0 <= py:
                            c.bits[py * 64 + (px >> 3)] &= (~(0x80 >> (px & 7))) & 0xFF
        cx += 6 * scale


def _heading(c: Canvas, x: int, text: str, scale: int = 2) -> None:
    c.text(x, c.y, text, scale)
    c.y += 7 * scale + 8


# ---- block renderers: draw inside x0..x1 starting at card.c.y, advancing it -----------------
def _greeting(card: Card, s: Mapping[str, Any], x0: int, x1: int) -> None:
    card.ornament("header", x0, x1)
    card.c.text(x0, card.c.y, str(s.get("greeting", "")).upper(), 3)
    card.c.y += 21 + 8
    if s.get("summary"):
        card.c.y += paragraph(card.c, x0, card.c.y, str(s["summary"]), 2, x1 - x0) + 2


def _metric(card: Card, s: Mapping[str, Any], x0: int, x1: int) -> None:
    c = card.c
    value = str(s.get("value", "--"))
    # The label wraps inside the tile, so a long label never runs over the border.
    for line in wrap_lines(_label(s.get("label", "")), 2, x1 - x0) or [""]:
        c.text(x0, c.y, line, 2)
        c.y += 7 * 2 + 4
    c.y += 4
    c.text(x0, c.y, value, 3)
    unit = str(s.get("unit") or "")
    unit_x = x0 + text_width(value, 3) + 6
    # The unit sits beside the value when it fits the tile, otherwise under it, never past the border.
    beside = bool(unit) and unit_x + text_width(unit, 2) <= x1
    if beside:
        c.text(unit_x, c.y + 14, unit, 2)
    c.y += 28
    if unit and not beside:
        c.text(x0, c.y, unit, 2)
        c.y += 7 * 2 + 4
    series = s.get("series")
    if isinstance(series, list) and len(series) > 1:
        c.y += 4
        line_graph(c, x0 + 4, c.y, x1 - 4, c.y + 36, series)
        c.y += 36 + 4


def _metric_rows(card: Card, s: Mapping[str, Any], x0: int, x1: int) -> None:
    c = card.c
    if s.get("title"):
        _heading(c, x0, _label(s["title"]))
    for r in list(s.get("rows", []))[:12]:
        card.icon(x0, c.y)
        unit = f" {r['unit']}" if r.get("unit") else ""
        c.row(x0 + 28, x1, c.y + 2, _label(r.get("label", "")), f"{r.get('value', '--')}{unit}", 2)
        c.y += 24


def _graph(card: Card, s: Mapping[str, Any], x0: int, x1: int) -> None:
    c = card.c
    _heading(c, x0, _label(s.get("title", "")))
    series = list(s.get("series", []))
    if len(series) > 1:
        plot = max(36, card.plot_h)
        line_graph(c, x0 + 4, c.y, x1 - 4, c.y + plot, series)
        c.y += plot + 16
        unit = f" {s['unit']}" if s.get("unit") else ""
        c.text(x0, c.y, f"{min(series):.1f}  ..  {series[-1]:.1f}{unit}", 2)
        c.y += 22


def _dog_counts(card: Card, s: Mapping[str, Any], x0: int, x1: int) -> None:
    c = card.c
    _heading(c, x0, "DOGS TODAY")
    for d in list(s.get("dogs", []))[:4]:
        card.icon(x0, c.y)
        tail = f"P{d.get('pee', 0)} O{d.get('poop', 0)} F{d.get('food', 0)} R{d.get('run', 0)}"
        c.row(x0 + 28, x1, c.y + 2, _label(d.get("name", "")), tail, 2)
        c.y += 24


def _message(card: Card, s: Mapping[str, Any], x0: int, x1: int) -> None:
    c = card.c
    card.ornament("header", x0, x1)
    if s.get("title"):
        _title_line(card, x0, x1, str(s["title"]))
    c.y += paragraph(c, x0, c.y, str(s.get("paragraph", "")), 2, x1 - x0) + 6
    if s.get("tip"):
        c.y += paragraph(c, x0, c.y, str(s["tip"]), 2, x1 - x0) + 4
    card.ornament("divider", x0, x1)
    if s.get("from"):
        c.text(x0, c.y, f"- {_label(s['from'])}", 2)
        c.y += 24


def _alert(card: Card, s: Mapping[str, Any], x0: int, x1: int) -> None:
    c = card.c
    card.ornament("header", x0, x1)
    _title_line(card, x0, x1, str(s.get("label", "")))
    if s.get("paragraph"):
        c.y += paragraph(c, x0, c.y, str(s["paragraph"]), 2, x1 - x0) + 6
    if s.get("action"):
        c.row(x0, x1, c.y, "ACTION", _label(s["action"]), 2)
        c.y += 24
    card.ornament("divider", x0, x1)


def _checklist(card: Card, s: Mapping[str, Any], x0: int, x1: int) -> None:
    c = card.c
    if s.get("title"):
        _heading(c, x0, _label(s["title"]))
    for item in list(s.get("items", []))[:12]:
        stamp_sprite(c, x0, c.y, "check" if item.get("checked") else "box")
        c.text(x0 + 26, c.y + 2, _label(item.get("text", "")), 2)
        c.y += 26


def _tip(card: Card, s: Mapping[str, Any], x0: int, x1: int) -> None:
    card.icon(x0, card.c.y)
    card.c.y += paragraph(card.c, x0 + 28, card.c.y, str(s.get("tip", "")), 2, x1 - x0 - 28) + 2


def _fact(card: Card, s: Mapping[str, Any], x0: int, x1: int) -> None:
    c = card.c
    card.ornament("header", x0, x1)
    c.y += paragraph(c, x0, c.y, str(s.get("paragraph", "")), 2, x1 - x0) + 4
    card.ornament("divider", x0, x1)
    c.text(x0, c.y, "FUN FACT", 2)
    c.y += 24


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
    return rows, notes


def _draw_row(c: Canvas, row: list[Placed]) -> None:
    row_units = max(p.units for p in row)
    top = c.y
    height = row_units * UNIT_H - GAP_V
    for p in row:
        # A graph takes the spare height of its card: the card height less padding, heading and footer.
        card = Card(c, p.block.mood, plot_h=max(36, height - 2 * PAD_V - 60))
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
    c.y += margin_bottom
    return c.crop(0), notes
