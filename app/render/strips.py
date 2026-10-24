"""Composable receipt strips: blocks in one shared card shell, drawn as 1-bit bitmaps.

A strip is an ordered list of blocks. Every block is a card in the same shell, so any mix stacks
cleanly. A strip holds at most five blocks, a greeting always starts a new strip, and every strip has
blank margins at the top and bottom so the cut is clean. Moods change only the ornament, the icon and
the accent. Size, grid and font never change.

The catalogue is app/render/system/blocks.json. The reference renderer is receipt-lab/lib/blocks.js,
and this port follows it step for step.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.render.canvas import Bitmap, Canvas, js_round, text_width

CATALOGUE: dict[str, Any] = json.loads((Path(__file__).parent / "system" / "blocks.json").read_text())
SHELL: dict[str, Any] = CATALOGUE["shell"]
MOODS: dict[str, dict[str, str]] = CATALOGUE["moods"]
BLOCKS: dict[str, dict[str, Any]] = CATALOGUE["blocks"]

WIDTH = SHELL["width_dots"]
SIDE = SHELL["side_margin_dots"]
LEFT = SIDE
RIGHT = WIDTH - SIDE
PAD = SHELL["card_padding_dots"]
GAP = SHELL["block_gap_dots"]
STROKE = SHELL["stroke_dots"]
RADIUS = SHELL["radius_dots"]
MAX_BLOCKS = SHELL["strip_rules"]["max_blocks"]
MARGIN_TOP = SHELL["margins"]["top_dots"]
MARGIN_BOTTOM = SHELL["margins"]["bottom_dots"]
NEUTRAL = "neutral"

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
    w = len(SPRITES["heart"][0]) * 3
    stamp_sprite(c, (x0 + x1 - w) // 2, y, "heart")
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
    per_line = max_w // (6 * scale)
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


# ---- the shell: one card, one ornament, the same outline for every block -----------------------
@dataclass
class Card:
    """Drawing state for one block: the canvas, and whether its ornament is already drawn."""

    c: Canvas
    ornamented: bool = False

    def ornament(self, mood: str, slot: str, x0: int, x1: int) -> int:
        """One ornament per card: the first header or divider the block asks for."""
        if self.ornamented:
            return 0
        name = MOODS[mood][slot]
        draw = ORNAMENTS.get(name)
        if draw is None:
            return 0
        h = draw(self.c, x0, x1, self.c.y) or 4
        self.c.y += h + 6
        self.ornamented = True
        return h + 6

    def icon(self, mood: str, x: int, y: int) -> None:
        name = MOODS[mood]["icon"]
        if name in SPRITES:
            stamp_sprite(self.c, x, y, name)


def _shell(c: Canvas, draw: Callable[[Card, int, int], None]) -> None:
    card = Card(c)
    top = c.y
    c.y += PAD
    draw(card, LEFT + PAD, RIGHT - PAD)
    bottom = c.y + PAD
    c.round_box(LEFT, top, RIGHT, bottom, RADIUS, STROKE)
    c.y = bottom + GAP


def _title_line(card: Card, mood: str, x0: int, text: str) -> None:
    """A pill for moods that ask for one, otherwise the icon with the label."""
    label = _label(text)
    c = card.c
    if MOODS[mood]["accent"] == "pill":
        w = text_width(label, 2) + 28
        h = 7 * 2 + 14
        c.round_box(x0, c.y, x0 + w, c.y + h, h // 2, 2)
        c.fill(x0 + 4, c.y + 4, x0 + w - 4, c.y + h - 4)
        c.text(x0 + 14, c.y + 7, label, 2)
        _erase_glyphs(c, x0 + 14, c.y + 7, label, 2)
        c.y += h + 8
    else:
        card.icon(mood, x0, c.y)
        c.text(x0 + 36, c.y + 2, label, 2)
        c.y += 30


def _erase_glyphs(c: Canvas, x: int, y: int, text: str, scale: int) -> None:
    """Clears the glyph dots, so the text shows white on a filled pill."""
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
                        if 0 <= px < WIDTH and 0 <= py:
                            c.bits[py * (WIDTH // 8) + (px >> 3)] &= ~(0x80 >> (px & 7)) & 0xFF
        cx += 6 * scale


def _heading(c: Canvas, x: int, text: str, scale: int = 2) -> None:
    c.text(x, c.y, text, scale)
    c.y += 7 * scale + 8


# ---- block renderers -----------------------------------------------------------------------------
def _greeting(card: Card, slots: Mapping[str, Any], mood: str, x0: int, x1: int) -> None:
    card.ornament(mood, "header", x0, x1)
    card.c.text(x0, card.c.y, str(slots.get("greeting", "")).upper(), 3)
    card.c.y += 21 + 8
    if slots.get("summary"):
        card.c.y += paragraph(card.c, x0, card.c.y, str(slots["summary"]), 2, x1 - x0) + 2


def _metric_tiles(card: Card, slots: Mapping[str, Any], mood: str, x0: int, x1: int) -> None:
    c = card.c
    metrics = list(slots.get("metrics", []))[:2]
    cw = (x1 - x0 - 10) // max(1, len(metrics))
    top = c.y
    has_series = False
    for i, m in enumerate(metrics):
        tx = x0 + i * (cw + 10)
        value = str(m.get("value", "--"))
        c.text(tx, top, _label(m.get("label", "")), 2)
        c.text(tx, top + 22, value, 3)
        if m.get("unit"):
            c.text(tx + text_width(value, 3) + 6, top + 22 + 14, str(m["unit"]), 2)
        series = m.get("series")
        if isinstance(series, list) and len(series) > 1:
            has_series = True
            line_graph(c, tx + 4, top + 56, tx + cw - 4, top + 92, series)
    c.y = top + (96 if has_series else 56)
    card.ornament(mood, "divider", x0, x1)


def _metric_rows(card: Card, slots: Mapping[str, Any], mood: str, x0: int, x1: int) -> None:
    c = card.c
    if slots.get("title"):
        _heading(c, x0, _label(slots["title"]))
    for r in list(slots.get("rows", []))[:6]:
        card.icon(mood, x0, c.y)
        unit = f" {r['unit']}" if r.get("unit") else ""
        c.row(x0 + 28, x1, c.y + 2, _label(r.get("label", "")), f"{r.get('value', '--')}{unit}", 2)
        c.y += 24


def _graph(card: Card, slots: Mapping[str, Any], mood: str, x0: int, x1: int) -> None:
    c = card.c
    _heading(c, x0, _label(slots.get("title", "")))
    series = list(slots.get("series", []))
    if len(series) > 1:
        line_graph(c, x0 + 4, c.y, x1 - 4, c.y + 56, series)
        c.y += 56 + 16
        unit = f" {slots['unit']}" if slots.get("unit") else ""
        c.text(x0, c.y, f"{min(series):.1f}  ..  {series[-1]:.1f}{unit}", 2)
        c.y += 22


def _dog_counts(card: Card, slots: Mapping[str, Any], mood: str, x0: int, x1: int) -> None:
    c = card.c
    _heading(c, x0, "DOGS TODAY")
    for d in list(slots.get("dogs", []))[:2]:
        card.icon(mood, x0, c.y)
        tail = f"P{d.get('pee', 0)} O{d.get('poop', 0)} F{d.get('food', 0)} R{d.get('run', 0)}"
        c.row(x0 + 28, x1, c.y + 2, _label(d.get("name", "")), tail, 2)
        c.y += 24


def _message(card: Card, slots: Mapping[str, Any], mood: str, x0: int, x1: int) -> None:
    c = card.c
    card.ornament(mood, "header", x0, x1)
    if slots.get("title"):
        _title_line(card, mood, x0, str(slots["title"]))
    c.y += paragraph(c, x0, c.y, str(slots.get("paragraph", "")), 2, x1 - x0) + 6
    if slots.get("tip"):
        c.y += paragraph(c, x0, c.y, str(slots["tip"]), 2, x1 - x0) + 4
    card.ornament(mood, "divider", x0, x1)
    if slots.get("from"):
        c.text(x0, c.y, f"- {_label(slots['from'])}", 2)
        c.y += 24


def _alert(card: Card, slots: Mapping[str, Any], mood: str, x0: int, x1: int) -> None:
    c = card.c
    card.ornament(mood, "header", x0, x1)
    _title_line(card, mood, x0, str(slots.get("label", "")))
    if slots.get("paragraph"):
        c.y += paragraph(c, x0, c.y, str(slots["paragraph"]), 2, x1 - x0) + 6
    if slots.get("action"):
        c.row(x0, x1, c.y, "ACTION", _label(slots["action"]), 2)
        c.y += 24
    card.ornament(mood, "divider", x0, x1)


def _checklist(card: Card, slots: Mapping[str, Any], mood: str, x0: int, x1: int) -> None:
    c = card.c
    if slots.get("title"):
        _heading(c, x0, _label(slots["title"]))
    for item in list(slots.get("items", []))[:8]:
        stamp_sprite(c, x0, c.y, "check" if item.get("checked") else "box")
        c.text(x0 + 26, c.y + 2, _label(item.get("text", "")), 2)
        c.y += 26


def _tip(card: Card, slots: Mapping[str, Any], mood: str, x0: int, x1: int) -> None:
    card.icon(mood, x0, card.c.y)
    card.c.y += paragraph(card.c, x0 + 28, card.c.y, str(slots.get("tip", "")), 2, x1 - x0 - 28) + 2


def _fact(card: Card, slots: Mapping[str, Any], mood: str, x0: int, x1: int) -> None:
    c = card.c
    card.ornament(mood, "header", x0, x1)
    c.y += paragraph(c, x0, c.y, str(slots.get("paragraph", "")), 2, x1 - x0) + 4
    card.ornament(mood, "divider", x0, x1)
    c.text(x0, c.y, "FUN FACT", 2)
    c.y += 24


RENDERERS: dict[str, Callable[[Card, Mapping[str, Any], str, int, int], None]] = {
    "greeting": _greeting,
    "metric_tiles": _metric_tiles,
    "metric_rows": _metric_rows,
    "graph": _graph,
    "dog_counts": _dog_counts,
    "message": _message,
    "alert": _alert,
    "checklist": _checklist,
    "tip": _tip,
    "fact": _fact,
}


# ---- blocks and strips ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Block:
    type: str
    slots: Mapping[str, Any]
    mood: str = NEUTRAL


def validate(block: Block) -> None:
    if block.type not in RENDERERS:
        raise ValueError(f"unknown block type: {block.type}")
    if block.mood not in MOODS:
        raise ValueError(f"unknown mood: {block.mood}")


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


def render_strip(
    blocks: Sequence[Block],
    *,
    margin_top: int = MARGIN_TOP,
    margin_bottom: int = MARGIN_BOTTOM,
) -> Bitmap:
    """Draws one strip with its margins. Raises ValueError for an unknown type or mood."""
    if not blocks:
        raise ValueError("a strip needs at least one block")
    if len(blocks) > MAX_BLOCKS:
        raise ValueError(f"a strip holds at most {MAX_BLOCKS} blocks")
    c = Canvas()
    c.y = margin_top
    for block in blocks:
        validate(block)
        render = RENDERERS[block.type]
        _shell(c, lambda card, x0, x1, b=block, r=render: r(card, b.slots, b.mood if b.mood in MOODS else NEUTRAL, x0, x1))
    c.y += margin_bottom
    return c.crop(0)
