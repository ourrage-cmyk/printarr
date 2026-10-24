"""Image-based receipt designs. Ports of the layouts in design-lab (round 4).

A design takes its values as arguments, so live Home Assistant data and sample data use the
same layout. Missing values print "NO DATA" in place of the value, so the rows stay put.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.render import system
from app.render.canvas import Bitmap, Canvas, solid_width
from app.render.strips import BODY, OUTER_L, OUTER_R, RADIUS, ROW, solid_wrap

LEFT = 14  # card edges, 14 dots from the paper edges
RIGHT = 498
PAD = 14  # inner padding
TOP = 14
NO_DATA = "NO DATA"


@dataclass(frozen=True)
class Variant:
    radius: int = 4  # Material 3 corner scale: 4, 8 or 12 dots
    scale: int = 2  # body text scale; the title uses scale + 1
    gap: int = 12  # space between cards
    row: int = 24  # space between rows of text
    head: int = 22  # space between the TODAY heading and the first row
    bar: int = 22  # from a segmented bar's label to the bar
    solid: bool = False  # body text in full-line Inter; the dot matrix is kept for titles only


@dataclass(frozen=True)
class Morning:
    """Values for the morning design. None means the value is missing."""

    summary: str  # one sentence under the greeting
    body_battery: int | None  # percent
    stress: int | None  # average level
    steps: int | None
    cpu: int | None  # percent
    ram: int | None  # percent


def card(c: Canvas, v: Variant, body: Callable[[int, int], None], x0: int = LEFT, x1: int = RIGHT) -> None:
    """An outlined card, sized to its content."""
    top = c.y
    c.y += PAD
    body(x0 + PAD, x1 - PAD)
    bottom = c.y + PAD
    c.round_box(x0, top, x1, bottom, v.radius, 2)
    c.y = bottom + v.gap


def title(c: Canvas, x: int, y: int, text: str, scale: int) -> None:
    """A title: the only text drawn in the dot matrix font."""
    c.text(x, y, text, scale)


def paragraph(c: Canvas, x: int, y: int, text: str, scale: int, max_w: int, solid: bool = False) -> int:
    """Word-wrapped text. Full-line Inter when solid, else capitals in the dot font. Returns the height used."""
    if solid:
        lines = solid_wrap(text, max_w)
        for i, line in enumerate(lines):
            c.solid(x, y + i * (7 * scale + 4), line, 21)
        return len(lines) * (7 * scale + 4)
    per_line = max_w // (6 * scale)
    lines: list[str] = []
    current = ""
    for word in text.upper().split():
        if current and len(current) + 1 + len(word) > per_line:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}" if current else word
    if current:
        lines.append(current)
    for i, line in enumerate(lines):
        c.text(x, y + i * (7 * scale + 4), line, scale)
    return len(lines) * (7 * scale + 4)


def _or_no_data(value: object) -> str:
    return NO_DATA if value is None else str(value)


def hello(c: Canvas, v: Variant, summary: str, x0: int, x1: int) -> None:
    title(c, x0, c.y, "HELLO YANNIC", v.scale + 1)
    c.y += 7 * (v.scale + 1) + 8
    c.y += paragraph(c, x0, c.y, summary, v.scale, x1 - x0, v.solid) + 2


def _row(c: Canvas, v: Variant, x0: int, x1: int, label: str, value: str) -> None:
    if v.solid:
        c.row_solid(x0, x1, c.y, label, value, 21)  # full-line label and value, dot leaders between
    else:
        c.row(x0, x1, c.y, label, value, v.scale)


def rows(c: Canvas, m: Morning, x0: int, x1: int, v: Variant = Variant()) -> None:
    title(c, x0, c.y, "TODAY", v.scale)
    c.y += v.head
    bb = m.body_battery
    _row(c, v, x0, x1, "BODY BATTERY", NO_DATA if bb is None else f"{bb}/100")
    c.y += v.row
    _row(c, v, x0, x1, "STRESS AVG", _or_no_data(m.stress))
    c.y += v.row
    _row(c, v, x0, x1, "STEPS", NO_DATA if m.steps is None else f"{m.steps:,}")
    c.y += v.row


def segbar(c: Canvas, m: Morning, x0: int, x1: int, v: Variant = Variant()) -> None:
    items = [
        ("BODY BATTERY", m.body_battery, "%"),
        ("CPU", m.cpu, "%"),
        ("RAM", m.ram, "%"),
    ]
    for label, percent, unit in items:
        value = NO_DATA if percent is None else f"{percent}{unit}"
        if v.solid:
            c.solid(x0, c.y, label, 21)
            c.solid(x1 - solid_width(value, 21), c.y, value, 21)
        else:
            c.text(x0, c.y, label, v.scale)
            c.text_right(x1, c.y, value, v.scale)
        # Same call as the Node renderer: bar height 10, 20 segments. The handoff spec says
        # 10 segments, 20 dots tall. Kept as rendered until the spec is confirmed. A missing
        # value draws an empty bar, so the card keeps its shape.
        fraction = 0 if percent is None else percent / 100
        c.seg_bar(x0, x1, c.y + v.bar, 10, fraction, 20)
        c.y += v.bar + 20


def system_card(
    c: Canvas,
    v: Variant,
    name: str,
    piece: str | None,
    body: Callable[[int, int], None],
    x0: int = LEFT,
    x1: int = RIGHT,
) -> None:
    """A card under the receipt system: the body, then at most one icon in the top-right corner."""
    top = c.y
    mark = system.ornament(piece) if piece else None
    body_x1 = x1 - PAD
    if mark is not None:
        body_x1 -= mark.width + system.spacing("m")  # keep the body clear of the icon
    c.y += PAD
    body(x0 + PAD, body_x1)
    bottom = c.y + PAD
    c.round_box(x0, top, x1, bottom, v.radius, 2)
    if mark is not None:
        c.stamp(mark, x1 - PAD - mark.width, top + PAD)
    c.y = bottom + v.gap


def morning_system(m: Morning) -> Bitmap:
    """The morning design under the receipt system: card radius and ornaments from app/render/system."""
    # Same card shell as the blocks: radius 4 and stroke 2 (app/render/system/blocks.json), body at scale 3.
    v = Variant(radius=RADIUS, scale=BODY, gap=system.spacing("m"), row=ROW, head=ROW, bar=7 * BODY + 5, solid=True)
    cards = system.decorations().get("morning", {})
    c = Canvas()
    c.y = TOP
    system_card(c, v, "hello", cards.get("hello"), lambda x0, x1: hello(c, v, m.summary, x0, x1), x0=OUTER_L, x1=OUTER_R)
    system_card(c, v, "rows", cards.get("rows"), lambda x0, x1: rows(c, m, x0, x1, v), x0=OUTER_L, x1=OUTER_R)
    system_card(c, v, "segbar", cards.get("segbar"), lambda x0, x1: segbar(c, m, x0, x1, v), x0=OUTER_L, x1=OUTER_R)
    return c.crop(12)


def morning_yannic(m: Morning, v: Variant = Variant()) -> Bitmap:
    """Hello, today's rows, and the segmented bars: the handoff's first design (B4-014)."""
    c = Canvas()
    c.y = TOP
    card(c, v, lambda x0, x1: hello(c, v, m.summary, x0, x1))
    card(c, v, lambda x0, x1: rows(c, m, x0, x1))
    card(c, v, lambda x0, x1: segbar(c, m, x0, x1))
    return c.crop(12)


# Sample values the Node reference used for B4-014, so the golden bitmap can be reproduced.
SAMPLE_MORNING = Morning(
    summary="Cloudy, 12 C. Bridget has been out twice. Cheap energy until 16:00.",
    body_battery=72,
    stress=24,
    steps=6120,
    cpu=18,
    ram=61,
)

