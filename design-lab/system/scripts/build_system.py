#!/usr/bin/env python3
"""Design system round: ornaments redrawn on the 5x7 dot pitch, plus a confirmation arena round.

Dot pitch: one logical pixel = 3 dots (PITCH). Every logical ink pixel is drawn as a 2x2 dot square
with a 1-dot gap, the same dot style as the winning 5x7 dot matrix in the font arena.
Ornaments are drawn on a logical grid and expanded, so they share one stroke weight (1 logical pixel)
and one pitch with the type.

Writes:
  assets/system/ornaments/<id>.png   the new family, 1-bit, one file per piece
  assets/system/sys-<concept>.png    confirmation round: new family on the system ticket
  assets/system/old-<concept>.png    confirmation round: the old ornament ticket (copied from pass 1)
  assets/system-manifest.json        id, name, type, size, pitch, source, licence, arena attributes
"""
import json
import math
import random
import shutil
from pathlib import Path

from PIL import Image, ImageDraw

from build_assets import GLYPHS_5X7, OFL, PROJECT, to_1bit  # noqa: F401  (OFL kept for the licence note)

HERE = Path(__file__).resolve().parent
ARENA = HERE.parent
OUT = ARENA / "assets" / "system"
PITCH = 3       # dots per logical pixel
DOT = 2         # dot size in dots, gap of 1
W = 512
PAD = 24        # 8 units

# ---------- logical drawing helpers ----------

def lcanvas(w, h):
    img = Image.new("L", (w, h), 0)
    return img, ImageDraw.Draw(img)


def expand(logical):
    """Logical pixels to dots: each ink pixel becomes a DOT x DOT square on the PITCH grid."""
    lw, lh = logical.size
    out = Image.new("L", (lw * PITCH, lh * PITCH), 0)
    d = ImageDraw.Draw(out)
    px = logical.load()
    for y in range(lh):
        for x in range(lw):
            if px[x, y] >= 128:
                d.rectangle([x * PITCH, y * PITCH, x * PITCH + DOT - 1, y * PITCH + DOT - 1], fill=255)
    return out


def text5x7(d, x, y, s):
    """5x7 glyphs on the logical grid (1 logical pixel per glyph dot)."""
    for i, ch in enumerate(s.upper()):
        g = GLYPHS_5X7.get(ch, GLYPHS_5X7[" "])
        for r, row in enumerate(g):
            for c, v in enumerate(row):
                if v == "#":
                    d.point((x + i * 6 + c, y + r), fill=255)


def star_pts(cx, cy, ro, ri, n=5):
    pts = []
    for i in range(n * 2):
        r = ro if i % 2 == 0 else ri
        a = -math.pi / 2 + i * math.pi / n
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def heart_pts(w, h, steps=48):
    pts = []
    for i in range(steps):
        t = 2 * math.pi * i / steps
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        pts.append(((x + 16) / 32 * (w - 1), (17 - y) / 30 * (h - 1)))
    return pts


# ---------- pieces: each returns a logical image ----------

PIECES = []  # dicts: concept, id, name, type, size (logical), fn, old (slug in pass 1)


def piece(concept, name, ptype, size, old=None):
    def reg(fn):
        PIECES.append({"concept": concept, "name": name, "type": ptype, "size": size, "fn": fn, "old": old})
        return fn
    return reg


# dividers and strips: logical width 149 (447 dots)
@piece("dotted-rule", "Dotted rule", "divider", (149, 2), old="dotted-rule")
def _(w, h):
    img, d = lcanvas(w, h)
    for x in range(0, w, 2):
        d.point((x, 0), fill=255)
    return img


@piece("perforation", "Perforation", "divider", (149, 3), old="perforation")
def _(w, h):
    img, d = lcanvas(w, h)
    for x in range(w):
        if x % 4 != 3:
            d.point((x, 1), fill=255)
    for x in range(0, w, 8):
        d.point((x, 0), fill=255)
        d.point((x, 2), fill=255)
    return img


@piece("tape-ticks", "Tape measure ticks", "divider", (149, 5), old="tape-ticks")
def _(w, h):
    img, d = lcanvas(w, h)
    d.line([0, 4, w - 1, 4], fill=255)
    for x in range(0, w, 2):
        length = 3 if x % 10 == 0 else 1
        d.line([x, 4 - length, x, 3], fill=255)
    return img


@piece("barcode-decor", "Barcode decor", "divider", (149, 5), old="barcode-decor")
def _(w, h):
    img, d = lcanvas(w, h)
    rng = random.Random(7)
    x = 0
    while x < w:
        bar = rng.choice([1, 1, 2])
        d.rectangle([x, 0, x + bar - 1, h - 1], fill=255)
        x += bar + rng.choice([1, 2])
    return img


@piece("wave", "Wave", "divider", (149, 5), old="wavy-line")
def _(w, h):
    img, d = lcanvas(w, h)
    pts = [(x, 2 + 1.5 * math.sin(x / 8 * 2 * math.pi)) for x in range(w)]
    for x, y in pts:
        d.point((x, round(y)), fill=255)
    return img


@piece("sun-strip", "Horizon sun strip", "strip", (149, 9), old="strip-horizon-sun")
def _(w, h):
    img, d = lcanvas(w, h)
    d.line([0, 8, w - 1, 8], fill=255)
    cx = w // 2
    d.pieslice([cx - 4, 4, cx + 4, 12], 180, 360, fill=255)
    for a in (200, 230, 270, 310, 340):
        r0, r1 = 6, 8
        d.line([cx + r0 * math.cos(math.radians(a)), 8 + r0 * math.sin(math.radians(a)),
                cx + r1 * math.cos(math.radians(a)), 8 + r1 * math.sin(math.radians(a))], fill=255)
    return img


# icons: 13 x 13 logical (39 dots)
@piece("battery", "Battery", "icon", (13, 13), old="icon-battery")
def _(w, h):
    img, d = lcanvas(w, h)
    d.rectangle([0, 3, 10, 9], outline=255)
    d.rectangle([11, 5, 12, 7], fill=255)
    for x in (2, 5, 8):
        d.rectangle([x, 5, x + 1, 7], fill=255)
    return img


@piece("heart", "Heart", "icon", (13, 13), old="icon-heart")
def _(w, h):
    img, d = lcanvas(w, h)
    d.polygon(heart_pts(w, h), fill=255)
    return img


@piece("star", "Star", "icon", (13, 13), old="icon-star")
def _(w, h):
    img, d = lcanvas(w, h)
    d.polygon(star_pts(6, 6.5, 6.5, 2.6), fill=255)
    return img


@piece("house", "House", "icon", (13, 13), old="icon-house")
def _(w, h):
    img, d = lcanvas(w, h)
    d.line([0, 6, 6, 0, 12, 6], fill=255)
    d.rectangle([2, 6, 10, 12], outline=255)
    d.rectangle([5, 9, 7, 12], fill=255)
    return img


@piece("bell", "Bell", "icon", (13, 13), old="icon-bell")
def _(w, h):
    img, d = lcanvas(w, h)
    d.pieslice([2, 1, 10, 9], 180, 360, fill=255)
    d.rectangle([2, 5, 10, 8], fill=255)
    d.polygon([(0, 9), (12, 9), (12, 10), (0, 10)], fill=255)
    d.rectangle([5, 11, 7, 12], fill=255)
    return img


@piece("dog", "Dog", "icon", (13, 13), old="icon-dog")
def _(w, h):
    img, d = lcanvas(w, h)
    d.ellipse([2, 5, 10, 9], fill=255)
    d.ellipse([8, 2, 12, 6], fill=255)
    d.polygon([(9, 2), (10, 0), (11, 2)], fill=255)
    d.line([2, 6, 0, 3], fill=255)
    d.rectangle([3, 9, 4, 12], fill=255)
    d.rectangle([8, 9, 9, 12], fill=255)
    return img


@piece("bone", "Bone", "icon", (13, 13), old="icon-bone")
def _(w, h):
    img, d = lcanvas(w, h)
    d.rectangle([3, 5, 9, 7], fill=255)
    for cx, cy in [(2, 4), (2, 8), (10, 4), (10, 8)]:
        d.ellipse([cx - 2, cy - 2, cx + 2, cy + 2], fill=255)
    return img


@piece("warning", "Warning triangle", "icon", (13, 13), old="icon-warning")
def _(w, h):
    img, d = lcanvas(w, h)
    d.polygon([(6, 0), (12, 12), (0, 12)], outline=255)
    d.rectangle([5, 4, 6, 8], fill=255)
    d.rectangle([5, 10, 6, 10], fill=255)
    return img


@piece("check-circle", "Check circle", "icon", (13, 13), old="icon-check-circle")
def _(w, h):
    img, d = lcanvas(w, h)
    d.ellipse([0, 0, 12, 12], outline=255)
    d.line([3, 6, 5, 9, 9, 3], fill=255)
    return img


@piece("stamp", "Stamp", "stamp", (24, 24), old="stamp-round")
def _(w, h):
    img, d = lcanvas(w, h)
    for a in range(0, 360, 20):
        x = 11.5 + 11 * math.cos(math.radians(a))
        y = 11.5 + 11 * math.sin(math.radians(a))
        d.point((round(x), round(y)), fill=255)
    d.ellipse([3, 3, 20, 20], outline=255)
    text5x7(d, 7, 8, "OK")
    return img


# fill pieces (no old twin; shown in the family and in the standalone set)
@piece("sun", "Sun", "icon", (13, 13))
def _(w, h):
    img, d = lcanvas(w, h)
    d.ellipse([4, 4, 8, 8], fill=255)
    for a in range(0, 360, 45):
        d.point((round(6 + 6 * math.cos(math.radians(a))), round(6 + 6 * math.sin(math.radians(a)))), fill=255)
    return img


@piece("moon", "Moon", "icon", (13, 13))
def _(w, h):
    img, d = lcanvas(w, h)
    d.ellipse([1, 1, 11, 11], fill=255)
    d.ellipse([4, 0, 13, 9], fill=0)
    return img


@piece("bolt", "Bolt", "icon", (13, 13))
def _(w, h):
    img, d = lcanvas(w, h)
    d.polygon([(8, 0), (2, 7), (6, 7), (4, 12), (11, 5), (7, 5), (9, 0)], fill=255)
    return img


@piece("drop", "Water drop", "icon", (13, 13))
def _(w, h):
    img, d = lcanvas(w, h)
    d.ellipse([1, 5, 11, 12], fill=255)
    d.polygon([(6, 0), (1, 8), (11, 8)], fill=255)
    return img


@piece("cloud", "Cloud", "icon", (13, 13))
def _(w, h):
    img, d = lcanvas(w, h)
    d.ellipse([0, 6, 6, 12], fill=255)
    d.ellipse([3, 2, 9, 9], fill=255)
    d.ellipse([7, 5, 12, 12], fill=255)
    d.rectangle([3, 8, 9, 12], fill=255)
    return img


@piece("coffee", "Coffee", "icon", (13, 13))
def _(w, h):
    img, d = lcanvas(w, h)
    d.rectangle([1, 4, 9, 11], fill=255)
    d.arc([8, 6, 12, 10], 270, 90, fill=255)
    d.line([0, 12, 11, 12], fill=255)
    d.point((3, 1), fill=255)
    d.point((6, 2), fill=255)
    return img


@piece("plant", "Plant", "icon", (13, 13))
def _(w, h):
    img, d = lcanvas(w, h)
    d.polygon([(3, 9), (10, 9), (9, 12), (4, 12)], fill=255)
    d.line([6, 9, 6, 4], fill=255)
    d.ellipse([1, 3, 5, 6], fill=255)
    d.ellipse([7, 0, 11, 4], fill=255)
    return img


@piece("arrow", "Arrow right", "icon", (13, 13))
def _(w, h):
    img, d = lcanvas(w, h)
    d.line([0, 6, 10, 6], fill=255)
    d.polygon([(7, 2), (12, 6), (7, 10)], fill=255)
    return img


@piece("corner", "Corner L", "corner", (5, 5))
def _(w, h):
    img, d = lcanvas(w, h)
    d.line([0, 0, 4, 0], fill=255)
    d.line([0, 0, 0, 4], fill=255)
    return img


@piece("card-outline", "Card outline, rounded", "border", (170, 60))
def _(w, h):
    img, d = lcanvas(w, h)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=4, outline=255)
    return img


# ---------- tickets ----------

def wrap_chars(text, per_line):
    words, lines, line = text.split(), [], ""
    for word in words:
        trial = (line + " " + word).strip()
        if len(trial) <= per_line:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def paste_dots(img, logical_img, x, y):
    img.paste(expand(logical_img), (x, y))


def dot_text(img, x, y, text, scale):
    """5x7 text at a dot scale: each glyph dot is scale x scale dots with a 1-dot gap when scale >= 3."""
    d = ImageDraw.Draw(img)
    cell = scale
    dot = scale - 1 if scale >= 3 else scale
    for i, ch in enumerate(text.upper()):
        g = GLYPHS_5X7.get(ch, GLYPHS_5X7[" "])
        for r, row in enumerate(g):
            for c, v in enumerate(row):
                if v == "#":
                    x0 = x + (i * 6 + c) * cell
                    y0 = y + r * cell
                    d.rectangle([x0, y0, x0 + dot - 1, y0 + dot - 1], fill=255)
    return x + len(text) * 6 * cell - scale


def text_width(text, scale):
    return len(text) * 6 * scale - scale


def solid_rule(img, y):
    ImageDraw.Draw(img).rectangle([PAD, y, W - PAD - 1, y + 1], fill=255)


def system_ticket(p=None, old_mode=False):
    """System ticket with a piece applied. Physical 512 wide, black ink on white."""
    img = Image.new("L", (W, 1400), 0)
    cw = W - 2 * PAD
    y = PAD
    kind = p["type"] if p else None

    # caption (scale 2 = cap 14)
    dot_text(img, PAD, y, "MORNING BRIEF / FRI 24 OCT", 2)
    y += 14 + 12

    # divider or strip slot; default is the solid rule
    if kind in ("divider", "strip"):
        paste_dots(img, p["fn"](*p["size"]), PAD, y)
        y += expand(p["fn"](*p["size"])).height + 14
    else:
        solid_rule(img, y)
        y += 2 + 14

    # headline (scale 4 = cap 28)
    dot_text(img, PAD, y, "GOOD MORNING", 4)
    y += 28 + 6
    dot_text(img, PAD, y, "YANNIC", 4)
    y += 28 + 18

    # display numerals (scale 6 = cap 42) with a unit at scale 2, bottom aligned
    dot_text(img, PAD, y, "23", 6)
    unit_x = PAD + text_width("23", 6) + 12
    dot_text(img, unit_x, y + 42 - 14, "MIN", 2)
    y += 42 + 14

    solid_rule(img, y)
    y += 2 + 12

    # label row and body (scale 3 = cap 21)
    dot_text(img, PAD, y, "COMMUTE", 3)
    dot_text(img, W - PAD - text_width("ON TIME", 3), y, "ON TIME", 3)
    y += 21 + 12
    # 5x7 at scale 3 is 18 dots per character, so 25 characters fit the 464-dot measure
    for line in ["LIGHT TRAFFIC ON THE A1.", "TWO MEETINGS BEFORE NOON,", "AND THE BINS GO OUT", "TONIGHT."]:
        dot_text(img, PAD, y, line, 3)
        y += 21 + 9
    y += 8

    # footer caption (scale 2)
    dot_text(img, PAD, y, "UPDATED 07:12 / EDINBURGH", 2)
    y += 14 + PAD
    H = y

    out = img.crop((0, 0, W, H))
    d = ImageDraw.Draw(out)
    inset = 12
    if kind == "border":
        # the new card outline replaces the default outline
        frame = expand(p["fn"](*p["size"]))
        frame = frame.resize((W - 2 * inset, H - 2 * inset), Image.Resampling.NEAREST)
        out.paste(frame, (inset, inset))
    else:
        dotted_outline(out, inset, H)
    if kind == "corner":
        c = expand(p["fn"](*p["size"]))
        out.paste(c, (inset + 6, inset + 6))
        out.paste(c.transpose(Image.Transpose.FLIP_LEFT_RIGHT), (W - inset - 6 - c.width, inset + 6))
        out.paste(c.transpose(Image.Transpose.FLIP_TOP_BOTTOM), (inset + 6, H - inset - 6 - c.height))
        out.paste(c.transpose(Image.Transpose.ROTATE_180), (W - inset - 6 - c.width, H - inset - 6 - c.height))
    if kind == "icon":
        icon = expand(p["fn"](*p["size"]))
        out.paste(icon, (W - PAD - icon.width, PAD))
    if kind == "stamp":
        stamp = expand(p["fn"](*p["size"]))
        out.paste(stamp, (W - PAD - stamp.width, PAD))
    return to_1bit(out)


def dotted_outline(img, inset, H):
    """Default card outline: a dotted hairline on the dot pitch (one logical pixel)."""
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = inset, inset, W - inset - 1, H - inset - 1
    for x in range(x0, x1 + 1, PITCH):
        d.rectangle([x, y0, x + DOT - 1, y0 + DOT - 1], fill=255)
        d.rectangle([x, y1 - DOT + 1, x + DOT - 1, y1], fill=255)
    for y in range(y0, y1 + 1, PITCH):
        d.rectangle([x0, y, x0 + DOT - 1, y + DOT - 1], fill=255)
        d.rectangle([x1 - DOT + 1, y, x1, y + DOT - 1], fill=255)


# ---------- main ----------

def standalone(p):
    img = expand(p["fn"](*p["size"]))
    return to_1bit(img)


def main():
    (OUT / "ornaments").mkdir(parents=True, exist_ok=True)
    manifest = []
    for p in PIECES:
        slug = p["concept"]
        img = standalone(p)
        rel = f"ornaments/orn-sys-{slug}.png"
        img.save(OUT / rel, optimize=True)
        manifest.append({
            "arena": "pieces", "id": f"sys-{slug}", "name": p["name"], "type": p["type"],
            "size": f"{img.width}x{img.height}", "pitch": PITCH, "dot": DOT,
            "file": f"assets/system/{rel}", "source": PROJECT + " (dot pitch 3)", "licence": PROJECT,
            "attributes": {"set": "system"},
        })

    # confirmation round: system family versus the old family, same concept each
    for p in PIECES:
        if not p["old"]:
            continue
        sys_ticket = system_ticket(p)
        sys_rel = f"sys-{p['concept']}.png"
        sys_ticket.save(OUT / sys_rel, optimize=True)
        old_src = ARENA / "assets" / "ornament-tickets" / f"orn-{p['old']}.png"
        old_rel = f"old-{p['concept']}.png"
        shutil.copyfile(old_src, OUT / old_rel)
        manifest.append({
            "arena": "system", "id": f"round-sys-{p['concept']}", "name": f"{p['name']} · system",
            "type": "round ticket", "size": f"{sys_ticket.width}x{sys_ticket.height}",
            "file": f"assets/system/{sys_rel}", "ticket": f"assets/system/{sys_rel}",
            "source": PROJECT, "licence": PROJECT, "attributes": {"set": "system"},
        })
        manifest.append({
            "arena": "system", "id": f"round-old-{p['concept']}", "name": f"{p['name']} · old",
            "type": "round ticket", "file": f"assets/system/{old_rel}", "ticket": f"assets/system/{old_rel}",
            "source": PROJECT, "licence": PROJECT, "attributes": {"set": "old"},
        })
        print("round", p["concept"], sys_ticket.size)

    (ARENA / "assets" / "system-manifest.json").write_text(json.dumps({
        "generated": "build/build_system.py",
        "pitch_dots": PITCH,
        "count": len(manifest),
        "assets": manifest,
    }, indent=2), encoding="utf8")
    print("wrote", len(manifest), "system assets;", sum(1 for p in PIECES if not p["old"]), "standalone pieces")


if __name__ == "__main__":
    main()
