#!/usr/bin/env python3
"""Builds the arena candidates: 1-bit tickets (512 dots wide) for fonts and ornaments.

Writes:
  assets/fonts/<id>.png             one font variant on the morning-briefing sample ticket
  assets/ornaments/<id>.png         the ornament on its own, 1-bit
  assets/ornament-tickets/<id>.png  the ornament applied on a sample ticket section
  assets/manifest.json              id, name, type, size, source and licence for every asset
Run: python build/build_assets.py   (from the arena folder, needs Pillow and glyphs-5x7.json)
"""
import json
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
ARENA = HERE.parent
FONT_DIR = HERE / "fonts-src"
OUT = ARENA / "assets"
W = 512
PAD = 24
SCRATCH_H = 1400

GLYPHS_5X7 = json.loads((HERE / "glyphs-5x7.json").read_text(encoding="utf8"))

# 3x5 pixel glyphs, written by hand for this build. Rows are strings, '#' is a dot.
GLYPHS_3X5 = {
    "0": ["###", "#.#", "#.#", "#.#", "###"], "1": [".#.", "##.", ".#.", ".#.", "###"],
    "2": ["###", "..#", "###", "#..", "###"], "3": ["###", "..#", "###", "..#", "###"],
    "4": ["#.#", "#.#", "###", "..#", "..#"], "5": ["###", "#..", "###", "..#", "###"],
    "6": ["###", "#..", "###", "#.#", "###"], "7": ["###", "..#", "..#", "..#", "..#"],
    "8": ["###", "#.#", "###", "#.#", "###"], "9": ["###", "#.#", "###", "..#", "###"],
    "A": [".#.", "#.#", "###", "#.#", "#.#"], "B": ["##.", "#.#", "##.", "#.#", "##."],
    "C": [".##", "#..", "#..", "#..", ".##"], "D": ["##.", "#.#", "#.#", "#.#", "##."],
    "E": ["###", "#..", "##.", "#..", "###"], "F": ["###", "#..", "##.", "#..", "#.."],
    "G": [".##", "#..", "#.#", "#.#", ".##"], "H": ["#.#", "#.#", "###", "#.#", "#.#"],
    "I": ["###", ".#.", ".#.", ".#.", "###"], "J": ["..#", "..#", "..#", "#.#", ".#."],
    "K": ["#.#", "##.", "#..", "##.", "#.#"], "L": ["#..", "#..", "#..", "#..", "###"],
    "M": ["#.#", "###", "###", "#.#", "#.#"], "N": ["##.", "#.#", "#.#", "#.#", "#.#"],
    "O": [".#.", "#.#", "#.#", "#.#", ".#."], "P": ["##.", "#.#", "##.", "#..", "#.."],
    "Q": [".#.", "#.#", "#.#", "###", "..#"], "R": ["##.", "#.#", "##.", "#.#", "#.#"],
    "S": [".##", "#..", ".#.", "..#", "##."], "T": ["###", ".#.", ".#.", ".#.", ".#."],
    "U": ["#.#", "#.#", "#.#", "#.#", "###"], "V": ["#.#", "#.#", "#.#", "#.#", ".#."],
    "W": ["#.#", "#.#", "###", "###", "#.#"], "X": ["#.#", "#.#", ".#.", "#.#", "#.#"],
    "Y": ["#.#", "#.#", ".#.", ".#.", ".#."], "Z": ["###", "..#", ".#.", "#..", "###"],
    ".": ["...", "...", "...", "...", ".#."], ",": ["...", "...", "...", ".#.", "#.."],
    ":": ["...", ".#.", "...", ".#.", "..."], "-": ["...", "...", "###", "...", "..."],
    "/": ["..#", "..#", ".#.", "#..", "#.."], " ": ["...", "...", "...", "...", "..."],
    "°": [".#.", "#.#", ".#.", "...", "..."],
}
GLYPHS_5X7["°"] = [".##..", "#..#.", "#..#.", ".##..", ".....", ".....", "....."]


def to_1bit(img):
    # Drawing is done in white ink on black; the output is black ink on white paper, like a printed ticket.
    return img.point(lambda v: 0 if v >= 128 else 255).convert("1", dither=Image.Dither.NONE)


def canvas(w, h):
    img = Image.new("L", (w, h), 0)
    return img, ImageDraw.Draw(img)


# ---------- text renderers: each has .cap (cap height in dots), width(text), draw(d, x, y, text) ----------

class TTFText:
    def __init__(self, path, cap):
        self.path = str(path)
        self.size = self._fit(cap)
        self.font = ImageFont.truetype(self.path, self.size)
        self.cap = self._cap(self.font)

    @staticmethod
    def _cap(font):
        box = font.getbbox("H", anchor="ls")
        return -box[1]

    def _fit(self, cap):
        lo, hi = 4, 400
        while lo < hi:
            mid = (lo + hi) // 2
            if self._cap(ImageFont.truetype(self.path, mid)) < cap:
                lo = mid + 1
            else:
                hi = mid
        return lo

    def width(self, text):
        return self.font.getlength(text)

    def draw(self, d, x, y, text):
        d.text((x, y + self.cap), text, font=self.font, fill=255, anchor="ls")


class BitmapText:
    """Dot-matrix glyph font. Each lit glyph pixel is drawn as a square dot with a one-dot gap."""

    def __init__(self, glyphs, gw, gh, cap):
        self.g = glyphs
        self.gw, self.gh = gw, gh
        self.s = max(1, round(cap / gh))
        self.cap = gh * self.s

    def _rows(self, ch):
        return self.g.get(ch.upper(), self.g.get(" "))

    def width(self, text):
        return len(text) * (self.gw + 1) * self.s - self.s

    def draw(self, d, x, y, text):
        s = self.s
        dot = s - 1 if s >= 3 else s
        for i, ch in enumerate(text):
            ox = x + i * (self.gw + 1) * s
            for py, row in enumerate(self._rows(ch)):
                for px, c in enumerate(row):
                    if c == "#":
                        x0 = ox + px * s
                        y0 = y + py * s
                        d.rectangle([x0, y0, x0 + dot - 1, y0 + dot - 1], fill=255)


class SevenSeg:
    """Seven-segment numerals drawn as rectangles. Only digits and '.' are supported."""
    SEG = {"0": "abcdef", "1": "bc", "2": "abdeg", "3": "abcdg", "4": "bcfg", "5": "acdfg",
           "6": "acdefg", "7": "abc", "8": "abcdefg", "9": "abcdfg"}

    def __init__(self, cap):
        self.cap = cap
        self.h = cap
        self.w = round(cap * 0.58)
        self.t = max(2, round(cap / 7))

    def _advance(self, ch):
        return self.t * 2 if ch == "." else self.w + self.t + self.t // 2

    def width(self, text):
        return sum(self._advance(c) for c in text) - self.t

    def draw(self, d, x, y, text):
        w, h, t = self.w, self.h, self.t
        mid = h // 2
        half = t // 2
        for ch in text:
            if ch == ".":
                d.rectangle([x, y + h - t, x + t - 1, y + h - 1], fill=255)
                x += self._advance(ch)
                continue
            segs = self.SEG.get(ch, "")
            boxes = {
                "a": [x + t, y, x + w - t - 1, y + t - 1],
                "b": [x + w - t, y + t, x + w - 1, y + mid - half - 1],
                "c": [x + w - t, y + mid + half, x + w - 1, y + h - t - 1],
                "d": [x + t, y + h - t, x + w - t - 1, y + h - 1],
                "e": [x, y + mid + half, x + t - 1, y + h - t - 1],
                "f": [x, y + t, x + t - 1, y + mid - half - 1],
                "g": [x + t, y + mid - half, x + w - t - 1, y + mid - half + t - 1],
            }
            for s in segs:
                d.rectangle(boxes[s], fill=255)
            x += self._advance(ch)


# ---------- sample layouts ----------

TIERS = {
    "A": {"body": 14, "head": 22, "num": 40},
    "B": {"body": 20, "head": 30, "num": 56},
}

# (id, file, family, kind, folder under OFL). All TTFs are SIL Open Font License 1.1.
TTF_FONTS = [
    ("silkscreen", "Silkscreen-Regular.ttf", "Silkscreen", "pixel", "silkscreen"),
    ("pressstart", "PressStart2P-Regular.ttf", "Press Start 2P", "pixel", "pressstart2p"),
    ("pixelify", "PixelifySans.ttf", "Pixelify Sans", "pixel", "pixelifysans"),
    ("vt323", "VT323-Regular.ttf", "VT323", "lcd", "vt323"),
    ("micro5", "Micro5-Regular.ttf", "Micro 5", "pixel", "micro5"),
    ("jersey10", "Jersey10-Regular.ttf", "Jersey 10", "pixel", "jersey10"),
    ("dotgothic", "DotGothic16-Regular.ttf", "DotGothic16", "dot", "dotgothic16"),
    ("handjet", "Handjet.ttf", "Handjet", "pixel-hand", "handjet"),
    ("majormono", "MajorMonoDisplay-Regular.ttf", "Major Mono Display", "mono-display", "majormonodisplay"),
    ("bungee", "Bungee-Regular.ttf", "Bungee", "display", "bungee"),
    ("rubikmono", "RubikMonoOne-Regular.ttf", "Rubik Mono One", "display", "rubikmonoone"),
    ("spacemono", "SpaceMono-Regular.ttf", "Space Mono", "mono", "spacemono"),
    ("plexmono", "IBMPlexMono-Regular.ttf", "IBM Plex Mono", "mono", "ibmplexmono"),
    ("jbmono", "JetBrainsMono.ttf", "JetBrains Mono", "mono", "jetbrainsmono"),
    ("sourcecode", "SourceCodePro.ttf", "Source Code Pro", "mono", "sourcecodepro"),
    ("sharetech", "ShareTechMono-Regular.ttf", "Share Tech Mono", "mono-lcd", "sharetechmono"),
    ("chivomono", "ChivoMono.ttf", "Chivo Mono", "mono", "chivomono"),
    ("inter", "Inter.ttf", "Inter", "sans", "inter"),
    ("dmsans", "DMSans.ttf", "DM Sans", "sans", "dmsans"),
    ("barlowcond", "BarlowCondensed-Regular.ttf", "Barlow Condensed", "condensed", "barlowcondensed"),
    ("oswald", "Oswald.ttf", "Oswald", "condensed", "oswald"),
    ("bebas", "BebasNeue-Regular.ttf", "Bebas Neue", "condensed-display", "bebasneue"),
    ("anton", "Anton-Regular.ttf", "Anton", "condensed-display", "anton"),
    ("plexserif", "IBMPlexSerif-Regular.ttf", "IBM Plex Serif", "serif", "ibmplexserif"),
    ("lora", "Lora.ttf", "Lora", "serif", "lora"),
    ("ptserif", "PTSerif-Regular.ttf", "PT Serif", "serif", "ptserif"),
    ("nunito", "Nunito.ttf", "Nunito", "rounded", "nunito"),
    ("quicksand", "Quicksand.ttf", "Quicksand", "rounded", "quicksand"),
    ("orbitron", "Orbitron.ttf", "Orbitron", "lcd-tech", "orbitron"),
    ("caveat", "Caveat.ttf", "Caveat", "hand", "caveat"),
    ("kalam", "Kalam-Regular.ttf", "Kalam", "hand", "kalam"),
    ("indie", "IndieFlower-Regular.ttf", "Indie Flower", "hand", "indieflower"),
    ("patrick", "PatrickHand-Regular.ttf", "Patrick Hand", "hand", "patrickhand"),
]
DOT_VARIANTS = {"silkscreen", "plexmono", "inter", "oswald", "vt323", "dmsans", "spacemono"}


def ofl_source(folder):
    return f"https://github.com/google/fonts/tree/main/ofl/{folder}"


OFL = "SIL Open Font License 1.1"
PROJECT = "Original, drawn for this project (receipt-lab arena)"


def make_fonts(kind):
    """Returns the list of font specs: each has a label, source, licence and a builder(tier)."""
    specs = []
    for fid, fname, family, fkind, folder in TTF_FONTS:
        path = FONT_DIR / fname
        for tier in ("A", "B"):
            specs.append({
                "id": f"font-{fid}-{tier}", "name": f"{family} {tier}", "family": family, "kind": fkind,
                "source": ofl_source(folder), "licence": OFL, "tier": tier, "dot": False,
                "build": (lambda p: lambda t: {
                    "body": TTFText(p, TIERS[t]["body"]),
                    "head": TTFText(p, TIERS[t]["head"]),
                    "num": TTFText(p, TIERS[t]["num"]),
                })(path),
            })
        if fid in DOT_VARIANTS:
            specs.append({
                "id": f"font-{fid}-dot", "name": f"{family} dot-matrix", "family": family, "kind": fkind + " + dot screen",
                "source": ofl_source(folder), "licence": OFL, "tier": "A", "dot": True,
                "build": (lambda p: lambda t: {
                    "body": TTFText(p, TIERS["B"]["body"]),
                    "head": TTFText(p, TIERS["B"]["head"]),
                    "num": TTFText(p, TIERS["B"]["num"]),
                })(path),
            })
    for tier in ("A", "B"):
        specs.append({
            "id": f"font-dotmatrix5x7-{tier}", "name": f"Dot matrix 5x7 {tier}", "family": "5x7 dot matrix",
            "kind": "dot-matrix native", "source": PROJECT, "licence": PROJECT, "tier": tier, "dot": False,
            "build": lambda t: {
                "body": BitmapText(GLYPHS_5X7, 5, 7, TIERS[t]["body"]),
                "head": BitmapText(GLYPHS_5X7, 5, 7, TIERS[t]["head"]),
                "num": BitmapText(GLYPHS_5X7, 5, 7, TIERS[t]["num"]),
            },
        })
        specs.append({
            "id": f"font-dotmatrix3x5-{tier}", "name": f"Pixel 3x5 {tier}", "family": "3x5 pixel",
            "kind": "pixel native", "source": PROJECT, "licence": PROJECT, "tier": tier, "dot": False,
            "build": lambda t: {
                "body": BitmapText(GLYPHS_3X5, 3, 5, TIERS[t]["body"]),
                "head": BitmapText(GLYPHS_3X5, 3, 5, TIERS[t]["head"]),
                "num": BitmapText(GLYPHS_3X5, 3, 5, TIERS[t]["num"]),
            },
        })
        specs.append({
            "id": f"font-sevenseg-{tier}", "name": f"7-segment numerals {tier}", "family": "7-segment + Share Tech Mono",
            "kind": "lcd numerals", "source": PROJECT + "; Share Tech Mono: " + ofl_source("sharetechmono"),
            "licence": PROJECT + " / " + OFL, "tier": tier, "dot": False,
            "build": (lambda p: lambda t: {
                "body": TTFText(p, TIERS[t]["body"]),
                "head": TTFText(p, TIERS[t]["head"]),
                "num": SevenSeg(TIERS[t]["num"]),
            })(FONT_DIR / "ShareTechMono-Regular.ttf"),
        })
    return specs


# ---------- morning-briefing sample ticket (fonts arena) ----------

def wrap(text, renderer, max_w):
    lines, line = [], ""
    for word in text.split():
        trial = (line + " " + word).strip()
        if renderer.width(trial) <= max_w:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def font_ticket(fonts, dot=False):
    img, d = canvas(W, SCRATCH_H)
    cw = W - 2 * PAD
    y = PAD
    body, head, num = fonts["body"], fonts["head"], fonts["num"]

    body.draw(d, PAD, y, "MORNING BRIEF / FRI 24 OCT")
    y += body.cap + 14
    d.line([PAD, y, W - PAD - 1, y], fill=255, width=1)
    y += 16

    head.draw(d, PAD, y, "GOOD MORNING")
    y += head.cap + 4
    head.draw(d, PAD, y, "YANNIC")
    y += head.cap + 18

    # Big number with a unit beside it, bottom-aligned.
    num.draw(d, PAD, y, "23")
    unit_x = PAD + num.width("23") + 10
    unit_y = y + num.cap - body.cap
    body.draw(d, unit_x, unit_y, "MIN")
    y += num.cap + 14

    d.line([PAD, y, W - PAD - 1, y], fill=255, width=1)
    y += 12
    body.draw(d, PAD, y, "COMMUTE")
    right = "ON TIME"
    body.draw(d, W - PAD - body.width(right), y, right)
    y += body.cap + 14

    for line in wrap("Light traffic on the A1. Two meetings before noon, and the bins go out tonight.", body, cw):
        body.draw(d, PAD, y, line)
        y += body.cap + 8
    y += 10
    body.draw(d, PAD, y, "UPDATED 07:12 / EDINBURGH")
    y += body.cap + PAD

    out = img.crop((0, 0, W, y))
    if dot:
        out = dot_screen(out)
    return to_1bit(out)


def dot_screen(img, cell=3):
    """Turns a grey-ish image into a dot-matrix screen: one dot per cell that has ink."""
    w, h = img.size
    small = img.resize((w // cell, h // cell), Image.Resampling.BOX)
    out, d = canvas(w, h)
    px = small.load()
    for cy in range(small.height):
        for cx in range(small.width):
            if px[cx, cy] >= 70:
                x0, y0 = cx * cell + 1, cy * cell + 1
                d.rectangle([x0, y0, x0 + 1, y0 + 1], fill=255)
    return out


# ---------- ornaments ----------

ORNAMENTS = []  # dicts: slug, name, type, size, fn(w, h) -> L image


def orn(slug, name, otype, size):
    def register(fn):
        ORNAMENTS.append({"slug": slug, "name": name, "type": otype, "size": size, "fn": fn})
        return fn
    return register


def star_points(cx, cy, ro, ri, n=5):
    pts = []
    for i in range(n * 2):
        r = ro if i % 2 == 0 else ri
        a = -math.pi / 2 + i * math.pi / n
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def heart_points(x0, y0, w, h, steps=72):
    pts = []
    for i in range(steps):
        t = 2 * math.pi * i / steps
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        pts.append((x0 + (x + 16) / 32 * w, y0 + (17 - y) / 30 * h))
    return pts


def scale_pts(pts, sx, sy):
    return [(x * sx, y * sy) for x, y in pts]


TEXT_FONT = None  # Inter, set in main()


def label_text(d, x, y, text):
    TEXT_FONT.draw(d, x, y, text)


# dividers (448 x 12)
@orn("dotted-rule", "Dotted rule", "divider", (448, 12))
def _(w, h):
    img, d = canvas(w, h)
    for x in range(0, w, 6):
        d.rectangle([x, h // 2 - 1, x + 1, h // 2], fill=255)
    return img


@orn("dash-rule", "Dash rule", "divider", (448, 12))
def _(w, h):
    img, d = canvas(w, h)
    for x in range(0, w, 18):
        d.rectangle([x, h // 2 - 1, x + 11, h // 2], fill=255)
    return img


@orn("double-hairline", "Double hairline", "divider", (448, 12))
def _(w, h):
    img, d = canvas(w, h)
    d.line([0, 3, w, 3], fill=255)
    d.line([0, 8, w, 8], fill=255)
    return img


@orn("thick-thin", "Thick over thin", "divider", (448, 12))
def _(w, h):
    img, d = canvas(w, h)
    d.rectangle([0, 2, w, 4], fill=255)
    d.line([0, 9, w, 9], fill=255)
    return img


@orn("wavy-line", "Wavy line", "divider", (448, 12))
def _(w, h):
    img, d = canvas(w, h)
    pts = [(x, h / 2 + 4 * math.sin(x / 16 * 2 * math.pi)) for x in range(w)]
    d.line(pts, fill=255, width=2)
    return img


@orn("zigzag", "Zigzag", "divider", (448, 12))
def _(w, h):
    img, d = canvas(w, h)
    pts = []
    for x in range(0, w + 8, 8):
        pts.append((x, 2 if (x // 8) % 2 == 0 else 10))
    d.line(pts, fill=255, width=2)
    return img


@orn("scallop", "Scallop edge", "divider", (448, 12))
def _(w, h):
    img, d = canvas(w, h)
    for x in range(0, w, 16):
        d.arc([x, 0, x + 16, 16], 0, 180, fill=255, width=2)
    return img


@orn("star-row", "Star row", "divider", (448, 12))
def _(w, h):
    img, d = canvas(w, h)
    d.line([0, 6, w, 6], fill=255)
    for x in range(8, w, 32):
        d.polygon(star_points(x, 6, 5, 2), fill=255)
    return img


@orn("dot-grid-strip", "Dot grid strip", "divider", (448, 12))
def _(w, h):
    img, d = canvas(w, h)
    for x in range(0, w, 8):
        d.rectangle([x, 2, x + 1, 3], fill=255)
        d.rectangle([x, 8, x + 1, 9], fill=255)
    return img


@orn("tape-ticks", "Tape measure ticks", "divider", (448, 12))
def _(w, h):
    img, d = canvas(w, h)
    d.line([0, 11, w, 11], fill=255)
    for i, x in enumerate(range(0, w, 4)):
        length = 9 if i % 5 == 0 else 4
        d.line([x, 11 - length, x, 10], fill=255)
    return img


@orn("cut-here", "Cut here dashes", "divider", (448, 12))
def _(w, h):
    img, d = canvas(w, h)
    for x in range(20, w, 12):
        d.rectangle([x, 5, x + 6, 6], fill=255)
    d.ellipse([0, 2, 8, 8], outline=255)
    d.line([12, 5, 18, 5], fill=255)
    return img


@orn("barcode-decor", "Barcode decor", "divider", (448, 12))
def _(w, h):
    img, d = canvas(w, h)
    rng = random.Random(7)
    x = 0
    while x < w:
        bar = rng.choice([1, 1, 2, 3])
        d.rectangle([x, 0, x + bar - 1, h - 1], fill=255)
        x += bar + rng.choice([1, 2, 3])
    return img


@orn("sawtooth", "Sawtooth", "divider", (448, 12))
def _(w, h):
    img, d = canvas(w, h)
    pts = []
    for x in range(0, w + 10, 10):
        pts.append((x, 11))
        pts.append((x + 5, 2))
    d.line(pts, fill=255, width=1)
    return img


@orn("perforation", "Perforation", "divider", (448, 12))
def _(w, h):
    img, d = canvas(w, h)
    for x in range(4, w, 10):
        d.ellipse([x - 2, 3, x + 2, 9], outline=255)
    return img


@orn("chevron-row", "Chevron row", "divider", (448, 12))
def _(w, h):
    img, d = canvas(w, h)
    for x in range(0, w, 16):
        d.line([x, 1, x + 5, 6], fill=255, width=2)
        d.line([x + 5, 6, x, 11], fill=255, width=2)
    return img


@orn("diamond-row", "Diamond row", "divider", (448, 12))
def _(w, h):
    img, d = canvas(w, h)
    d.line([0, 6, w, 6], fill=255)
    for x in range(8, w, 16):
        d.polygon([(x, 1), (x + 4, 6), (x, 11), (x - 4, 6)], fill=255)
    return img


@orn("plus-row", "Plus row", "divider", (448, 12))
def _(w, h):
    img, d = canvas(w, h)
    for x in range(6, w, 14):
        d.line([x - 3, 6, x + 3, 6], fill=255, width=1)
        d.line([x, 3, x, 9], fill=255, width=1)
    return img


@orn("ellipsis-dots", "Ellipsis dots", "divider", (448, 12))
def _(w, h):
    img, d = canvas(w, h)
    for x in range(w // 2 - 40, w // 2 + 40, 12):
        d.rectangle([x, 5, x + 3, 8], fill=255)
    return img


@orn("hatch-strip", "Hatch strip", "divider", (448, 12))
def _(w, h):
    img, d = canvas(w, h)
    for x in range(-12, w, 6):
        d.line([x, h, x + h, 0], fill=255)
    return img


@orn("checker-strip", "Checker strip", "divider", (448, 12))
def _(w, h):
    img, d = canvas(w, h)
    for i, x in enumerate(range(0, w, 6)):
        if i % 2 == 0:
            d.rectangle([x, 0, x + 5, 11], fill=255)
    return img


@orn("sine-thick", "Thick sine", "divider", (448, 12))
def _(w, h):
    img, d = canvas(w, h)
    pts = [(x, h / 2 + 4 * math.sin(x / 10 * 2 * math.pi)) for x in range(w)]
    d.line(pts, fill=255, width=4)
    return img


@orn("dotted-wave", "Dotted wave", "divider", (448, 12))
def _(w, h):
    img, d = canvas(w, h)
    for x in range(0, w, 4):
        y = h / 2 + 4 * math.sin(x / 16 * 2 * math.pi)
        d.rectangle([x, int(y), x + 1, int(y) + 1], fill=255)
    return img


@orn("arrow-rule", "Arrow rule", "divider", (448, 12))
def _(w, h):
    img, d = canvas(w, h)
    d.line([0, 6, w - 10, 6], fill=255)
    d.polygon([(w - 1, 6), (w - 10, 1), (w - 10, 11)], fill=255)
    return img


# borders (512 x H, drawn over the section; the tile is 512 x 256 when exported)
@orn("outline-round-12", "Outline, rounded 12", "border", (512, 256))
def _(w, h):
    img, d = canvas(w, h)
    d.rounded_rectangle([8, 8, w - 9, h - 9], radius=12, outline=255, width=2)
    return img


@orn("outline-hairline", "Outline, hairline", "border", (512, 256))
def _(w, h):
    img, d = canvas(w, h)
    d.rectangle([8, 8, w - 9, h - 9], outline=255, width=1)
    return img


@orn("outline-pill", "Outline, pill", "border", (512, 256))
def _(w, h):
    img, d = canvas(w, h)
    d.rounded_rectangle([8, 8, w - 9, h - 9], radius=(h - 16) // 2, outline=255, width=2)
    return img


@orn("outline-chamfer", "Outline, chamfered corners", "border", (512, 256))
def _(w, h):
    img, d = canvas(w, h)
    c = 16
    pts = [(8 + c, 8), (w - 9 - c, 8), (w - 9, 8 + c), (w - 9, h - 9 - c),
           (w - 9 - c, h - 9), (8 + c, h - 9), (8, h - 9 - c), (8, 8 + c), (8 + c, 8)]
    d.line(pts, fill=255, width=2)
    return img


@orn("double-outline", "Double outline", "border", (512, 256))
def _(w, h):
    img, d = canvas(w, h)
    d.rectangle([8, 8, w - 9, h - 9], outline=255, width=1)
    d.rectangle([13, 13, w - 14, h - 14], outline=255, width=1)
    return img


@orn("dotted-outline", "Dotted outline", "border", (512, 256))
def _(w, h):
    img, d = canvas(w, h)
    for x in range(8, w - 8, 6):
        d.rectangle([x, 8, x + 1, 9], fill=255)
        d.rectangle([x, h - 10, x + 1, h - 9], fill=255)
    for y in range(8, h - 8, 6):
        d.rectangle([8, y, 9, y + 1], fill=255)
        d.rectangle([w - 10, y, w - 9, y + 1], fill=255)
    return img


@orn("notched-stub", "Ticket stub notches", "border", (512, 256))
def _(w, h):
    img, d = canvas(w, h)
    d.rectangle([8, 8, w - 9, h - 9], outline=255, width=1)
    for cx in (8, w - 9):
        d.ellipse([cx - 8, h // 2 - 8, cx + 8, h // 2 + 8], fill=0, outline=255)
    return img


@orn("corner-brackets", "Corner brackets only", "border", (512, 256))
def _(w, h):
    img, d = canvas(w, h)
    L = 28
    for x, y, dx, dy in [(8, 8, 1, 1), (w - 9, 8, -1, 1), (8, h - 9, 1, -1), (w - 9, h - 9, -1, -1)]:
        d.line([x, y, x + dx * L, y], fill=255, width=2)
        d.line([x, y, x, y + dy * L], fill=255, width=2)
    return img


@orn("dashed-outline", "Dashed outline", "border", (512, 256))
def _(w, h):
    img, d = canvas(w, h)
    for x in range(8, w - 8, 12):
        d.line([x, 8, min(x + 6, w - 9), 8], fill=255)
        d.line([x, h - 9, min(x + 6, w - 9), h - 9], fill=255)
    for y in range(8, h - 8, 12):
        d.line([8, y, 8, min(y + 6, h - 9)], fill=255)
        d.line([w - 9, y, w - 9, min(y + 6, h - 9)], fill=255)
    return img


@orn("folder-tab", "Folder tab outline", "border", (512, 256))
def _(w, h):
    img, d = canvas(w, h)
    d.line([8, h - 9, w - 9, h - 9, w - 9, 40, 170, 40, 150, 8, 8, 8, 8, h - 9], fill=255, width=2)
    return img


@orn("perforated-edge", "Perforated edge", "border", (512, 256))
def _(w, h):
    img, d = canvas(w, h)
    d.rectangle([8, 8, w - 9, h - 9], outline=255, width=1)
    for x in range(14, w - 14, 14):
        d.ellipse([x - 2, 4, x + 2, 8], fill=0, outline=255)
        d.ellipse([x - 2, h - 9, x + 2, h - 5], fill=0, outline=255)
    return img


# corners (32 x 32), placed in four orientations
@orn("corner-l-thin", "Corner L, thin", "corner", (32, 32))
def _(w, h):
    img, d = canvas(w, h)
    d.line([0, 0, 31, 0], fill=255)
    d.line([0, 0, 0, 31], fill=255)
    return img


@orn("corner-l-thick", "Corner L, thick", "corner", (32, 32))
def _(w, h):
    img, d = canvas(w, h)
    d.rectangle([0, 0, 23, 2], fill=255)
    d.rectangle([0, 0, 2, 23], fill=255)
    return img


@orn("corner-arc", "Corner arc", "corner", (32, 32))
def _(w, h):
    img, d = canvas(w, h)
    d.arc([0, 0, 63, 63], 0, 90, fill=255, width=2)
    return img.resize((w, h))


@orn("corner-dots", "Corner dot cluster", "corner", (32, 32))
def _(w, h):
    img, d = canvas(w, h)
    for x, y in [(2, 2), (8, 2), (2, 8), (14, 2), (2, 14)]:
        d.rectangle([x, y, x + 2, y + 2], fill=255)
    return img


@orn("corner-stair", "Corner stair", "corner", (32, 32))
def _(w, h):
    img, d = canvas(w, h)
    for i in range(4):
        d.rectangle([0, i * 8, 23 - i * 6, i * 8 + 1], fill=255)
        d.rectangle([i * 8, 0, i * 8 + 1, 23 - i * 6], fill=255)
    return img


@orn("corner-double-l", "Corner double L", "corner", (32, 32))
def _(w, h):
    img, d = canvas(w, h)
    d.line([0, 0, 27, 0], fill=255)
    d.line([0, 0, 0, 27], fill=255)
    d.line([5, 5, 22, 5], fill=255)
    d.line([5, 5, 5, 22], fill=255)
    return img


@orn("corner-round-bracket", "Corner round bracket", "corner", (32, 32))
def _(w, h):
    img, d = canvas(w, h)
    d.arc([0, 0, 30, 30], 180, 270, fill=255, width=2)
    d.line([15, 0, 31, 0], fill=255, width=2)
    d.line([0, 15, 0, 31], fill=255, width=2)
    return img


# headers (448 x 40), each carries its own text in Inter
@orn("header-underline", "Header, underline", "header", (448, 40))
def _(w, h):
    img, d = canvas(w, h)
    label_text(d, 0, 4, "HELLO, YANNIC")
    d.rectangle([0, h - 3, w, h - 1], fill=255)
    return img


@orn("header-pill", "Header, pill label", "header", (448, 40))
def _(w, h):
    img, d = canvas(w, h)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=(h - 1) // 2, outline=255, width=2)
    label_text(d, 20, 9, "HELLO, YANNIC")
    return img


@orn("header-bubble", "Header, speech bubble", "header", (448, 40))
def _(w, h):
    img, d = canvas(w, h)
    d.rounded_rectangle([0, 0, 300, h - 9], radius=10, outline=255, width=2)
    d.polygon([(20, h - 9), (34, h - 9), (18, h - 1)], fill=255)
    label_text(d, 14, 9, "HELLO, YANNIC")
    return img


@orn("header-arrow", "Header, arrow lead", "header", (448, 40))
def _(w, h):
    img, d = canvas(w, h)
    d.polygon([(0, 14), (18, 14), (18, 8), (28, 19), (18, 30), (18, 24), (0, 24)], fill=255)
    label_text(d, 40, 8, "HELLO, YANNIC")
    return img


@orn("header-dot-lead", "Header, dot lead", "header", (448, 40))
def _(w, h):
    img, d = canvas(w, h)
    d.rectangle([0, 15, 9, 24], fill=255)
    label_text(d, 20, 8, "HELLO, YANNIC")
    return img


@orn("header-brackets", "Header, bracket frame", "header", (448, 40))
def _(w, h):
    img, d = canvas(w, h)
    d.line([0, 0, 0, h - 1], fill=255, width=2)
    d.line([0, 0, 10, 0], fill=255, width=2)
    d.line([0, h - 1, 10, h - 1], fill=255, width=2)
    d.line([w - 1, 0, w - 1, h - 1], fill=255, width=2)
    d.line([w - 11, 0, w - 1, 0], fill=255, width=2)
    d.line([w - 11, h - 1, w - 1, h - 1], fill=255, width=2)
    label_text(d, 22, 8, "HELLO, YANNIC")
    return img


@orn("header-double-rule", "Header, double rule", "header", (448, 40))
def _(w, h):
    img, d = canvas(w, h)
    d.line([0, 2, w, 2], fill=255)
    d.line([0, 5, w, 5], fill=255)
    label_text(d, 0, 12, "HELLO, YANNIC")
    d.line([0, h - 3, w, h - 3], fill=255)
    return img


@orn("header-wave", "Header, wave underline", "header", (448, 40))
def _(w, h):
    img, d = canvas(w, h)
    label_text(d, 0, 4, "HELLO, YANNIC")
    pts = [(x, h - 4 + 2 * math.sin(x / 6)) for x in range(w)]
    d.line(pts, fill=255, width=2)
    return img


@orn("header-number-box", "Header, number box", "header", (448, 40))
def _(w, h):
    img, d = canvas(w, h)
    d.rectangle([0, 0, 35, h - 1], outline=255, width=2)
    label_text(d, 8, 9, "01")
    label_text(d, 50, 8, "HELLO, YANNIC")
    return img


@orn("header-chamfer-box", "Header, chamfer box", "header", (448, 40))
def _(w, h):
    img, d = canvas(w, h)
    c = 10
    d.line([c, 0, 300, 0, 300 + c, c, 300 + c, h - 1, c, h - 1, 0, h - c, 0, c, c, 0], fill=255, width=2)
    label_text(d, 22, 9, "HELLO, YANNIC")
    return img


# bullets (16 x 16)
@orn("bullet-square", "Bullet, square dot", "bullet", (16, 16))
def _(w, h):
    img, d = canvas(w, h)
    d.rectangle([4, 4, 9, 9], fill=255)
    return img


@orn("bullet-ring", "Bullet, ring", "bullet", (16, 16))
def _(w, h):
    img, d = canvas(w, h)
    d.ellipse([2, 2, 13, 13], outline=255, width=2)
    return img


@orn("bullet-disc", "Bullet, disc", "bullet", (16, 16))
def _(w, h):
    img, d = canvas(w, h)
    d.ellipse([2, 2, 13, 13], fill=255)
    return img


@orn("bullet-diamond", "Bullet, diamond", "bullet", (16, 16))
def _(w, h):
    img, d = canvas(w, h)
    d.polygon([(8, 1), (14, 8), (8, 14), (2, 8)], fill=255)
    return img


@orn("bullet-dash", "Bullet, dash", "bullet", (16, 16))
def _(w, h):
    img, d = canvas(w, h)
    d.rectangle([2, 7, 13, 8], fill=255)
    return img


@orn("bullet-star", "Bullet, star", "bullet", (16, 16))
def _(w, h):
    img, d = canvas(w, h)
    d.polygon(star_points(8, 8, 7, 3), fill=255)
    return img


@orn("bullet-arrow", "Bullet, arrow", "bullet", (16, 16))
def _(w, h):
    img, d = canvas(w, h)
    d.polygon([(3, 2), (13, 8), (3, 14)], fill=255)
    return img


@orn("bullet-checkbox", "Bullet, checkbox", "bullet", (16, 16))
def _(w, h):
    img, d = canvas(w, h)
    d.rectangle([1, 1, 14, 14], outline=255, width=2)
    return img


@orn("bullet-checked", "Bullet, checked box", "bullet", (16, 16))
def _(w, h):
    img, d = canvas(w, h)
    d.rectangle([1, 1, 14, 14], outline=255, width=2)
    d.line([4, 8, 7, 11, 12, 4], fill=255, width=2)
    return img


# icons (48 x 48)
@orn("icon-sun", "Sun", "icon", (48, 48))
def _(w, h):
    img, d = canvas(w, h)
    d.ellipse([14, 14, 34, 34], fill=255)
    for a in range(0, 360, 45):
        r0, r1 = 20, 23
        x0, y0 = 24 + r0 * math.cos(math.radians(a)), 24 + r0 * math.sin(math.radians(a))
        x1, y1 = 24 + r1 * math.cos(math.radians(a)), 24 + r1 * math.sin(math.radians(a))
        d.line([x0, y0, x1, y1], fill=255, width=3)
    return img


@orn("icon-moon", "Moon", "icon", (48, 48))
def _(w, h):
    img, d = canvas(w, h)
    d.ellipse([8, 6, 40, 42], fill=255)
    d.ellipse([18, 2, 46, 36], fill=0)
    return img


@orn("icon-bolt", "Bolt", "icon", (48, 48))
def _(w, h):
    img, d = canvas(w, h)
    d.polygon([(28, 3), (10, 27), (22, 27), (18, 45), (38, 19), (26, 19), (32, 3)], fill=255)
    return img


@orn("icon-battery", "Battery", "icon", (48, 48))
def _(w, h):
    img, d = canvas(w, h)
    d.rectangle([3, 14, 40, 34], outline=255, width=3)
    d.rectangle([41, 21, 45, 27], fill=255)
    for x in (9, 18, 27):
        d.rectangle([x, 19, x + 6, 29], fill=255)
    return img


@orn("icon-heart", "Heart", "icon", (48, 48))
def _(w, h):
    img, d = canvas(w, h)
    d.polygon(heart_points(4, 6, 40, 36), fill=255)
    return img


@orn("icon-coffee", "Coffee", "icon", (48, 48))
def _(w, h):
    img, d = canvas(w, h)
    d.rectangle([8, 18, 30, 40], fill=255)
    d.arc([26, 22, 42, 38], 270, 90, fill=255, width=3)
    d.line([4, 43, 36, 43], fill=255, width=3)
    for x in (14, 22):
        d.line([x, 4, x - 2, 10, x + 2, 14], fill=255)
    return img


@orn("icon-bone", "Bone", "icon", (48, 48))
def _(w, h):
    img, d = canvas(w, h)
    d.rectangle([12, 20, 36, 28], fill=255)
    for cx, cy in [(10, 18), (10, 30), (38, 18), (38, 30)]:
        d.ellipse([cx - 6, cy - 6, cx + 6, cy + 6], fill=255)
    return img


@orn("icon-dog", "Dog", "icon", (48, 48))
def _(w, h):
    img, d = canvas(w, h)
    d.ellipse([10, 20, 38, 36], fill=255)
    d.ellipse([32, 12, 44, 26], fill=255)
    d.polygon([(34, 12), (36, 3), (40, 12)], fill=255)
    d.line([10, 22, 4, 12], fill=255, width=3)
    d.rectangle([12, 34, 16, 44], fill=255)
    d.rectangle([28, 34, 32, 44], fill=255)
    d.rectangle([44, 18, 47, 20], fill=255)
    return img


@orn("icon-plant", "Plant", "icon", (48, 48))
def _(w, h):
    img, d = canvas(w, h)
    d.polygon([(12, 32), (36, 32), (32, 44), (16, 44)], fill=255)
    d.line([24, 32, 24, 14], fill=255, width=2)
    d.ellipse([10, 12, 24, 24], fill=255)
    d.ellipse([24, 4, 38, 18], fill=255)
    return img


@orn("icon-drop", "Water drop", "icon", (48, 48))
def _(w, h):
    img, d = canvas(w, h)
    d.ellipse([10, 18, 38, 44], fill=255)
    d.polygon([(24, 3), (12, 26), (36, 26)], fill=255)
    return img


@orn("icon-star", "Star", "icon", (48, 48))
def _(w, h):
    img, d = canvas(w, h)
    d.polygon(star_points(24, 25, 22, 9), fill=255)
    return img


@orn("icon-stamp", "Stamp", "icon", (48, 48))
def _(w, h):
    img, d = canvas(w, h)
    d.rectangle([4, 6, 44, 44], outline=255, width=2)
    d.ellipse([14, 14, 34, 34], outline=255, width=2)
    return img


@orn("icon-arrow-right", "Arrow right", "icon", (48, 48))
def _(w, h):
    img, d = canvas(w, h)
    d.line([6, 24, 36, 24], fill=255, width=4)
    d.polygon([(30, 12), (42, 24), (30, 36)], fill=255)
    return img


@orn("icon-arrow-up", "Arrow up", "icon", (48, 48))
def _(w, h):
    img, d = canvas(w, h)
    d.line([24, 40, 24, 12], fill=255, width=4)
    d.polygon([(12, 18), (24, 6), (36, 18)], fill=255)
    return img


@orn("icon-cloud", "Cloud", "icon", (48, 48))
def _(w, h):
    img, d = canvas(w, h)
    d.ellipse([4, 22, 24, 40], fill=255)
    d.ellipse([16, 12, 38, 34], fill=255)
    d.ellipse([28, 22, 44, 40], fill=255)
    d.rectangle([12, 30, 40, 40], fill=255)
    return img


@orn("icon-walk", "Walker", "icon", (48, 48))
def _(w, h):
    img, d = canvas(w, h)
    d.ellipse([22, 4, 30, 12], fill=255)
    d.line([26, 14, 22, 28], fill=255, width=4)
    d.line([22, 28, 14, 44], fill=255, width=4)
    d.line([22, 28, 34, 40], fill=255, width=4)
    d.line([26, 18, 36, 26], fill=255, width=3)
    d.line([26, 18, 14, 24], fill=255, width=3)
    return img


@orn("icon-house", "House", "icon", (48, 48))
def _(w, h):
    img, d = canvas(w, h)
    d.line([4, 24, 24, 5, 44, 24], fill=255, width=3)
    d.rectangle([10, 24, 38, 43], outline=255, width=3)
    d.rectangle([20, 32, 28, 43], fill=255)
    return img


@orn("icon-thermo", "Thermometer", "icon", (48, 48))
def _(w, h):
    img, d = canvas(w, h)
    d.rounded_rectangle([18, 4, 30, 34], radius=6, outline=255, width=3)
    d.ellipse([14, 30, 34, 44], fill=255)
    d.rectangle([22, 18, 26, 40], fill=255)
    return img


@orn("icon-check-circle", "Check circle", "icon", (48, 48))
def _(w, h):
    img, d = canvas(w, h)
    d.ellipse([4, 4, 44, 44], outline=255, width=3)
    d.line([14, 24, 21, 32, 35, 16], fill=255, width=4)
    return img


@orn("icon-warning", "Warning triangle", "icon", (48, 48))
def _(w, h):
    img, d = canvas(w, h)
    d.polygon([(24, 4), (45, 42), (3, 42)], outline=255, width=3)
    d.rectangle([22, 16, 26, 31], fill=255)
    d.rectangle([22, 35, 26, 39], fill=255)
    return img


@orn("icon-bell", "Bell", "icon", (48, 48))
def _(w, h):
    img, d = canvas(w, h)
    d.pieslice([10, 6, 38, 38], 180, 360, fill=255)
    d.rectangle([10, 22, 38, 34], fill=255)
    d.polygon([(6, 34), (42, 34), (46, 40), (2, 40)], fill=255)
    d.ellipse([20, 40, 28, 46], fill=255)
    return img


# strips (448 x 40) and tiles
@orn("strip-horizon-sun", "Horizon sun strip", "strip", (448, 40))
def _(w, h):
    img, d = canvas(w, h)
    d.line([0, 32, w, 32], fill=255, width=2)
    d.pieslice([w // 2 - 14, 18, w // 2 + 14, 46], 180, 360, fill=255)
    for a in range(200, 350, 25):
        x0 = w // 2 + 20 * math.cos(math.radians(a))
        y0 = 32 + 20 * math.sin(math.radians(a))
        x1 = w // 2 + 26 * math.cos(math.radians(a))
        y1 = 32 + 26 * math.sin(math.radians(a))
        d.line([x0, y0, x1, y1], fill=255, width=2)
    return img


@orn("strip-moon-stars", "Moon and stars strip", "strip", (448, 40))
def _(w, h):
    img, d = canvas(w, h)
    d.line([0, 34, w, 34], fill=255)
    d.ellipse([12, 4, 36, 30], fill=255)
    d.ellipse([22, 0, 42, 22], fill=0)
    for x in range(70, w, 46):
        d.polygon(star_points(x, 14, 6, 2.5), fill=255)
    return img


@orn("strip-barcode", "Barcode strip", "strip", (448, 40))
def _(w, h):
    img, d = canvas(w, h)
    rng = random.Random(21)
    x = 0
    while x < w:
        bar = rng.choice([1, 2, 3, 4])
        d.rectangle([x, 0, x + bar - 1, h - 1], fill=255)
        x += bar + rng.choice([2, 3])
    return img


@orn("strip-weather", "Weather strip", "strip", (448, 40))
def _(w, h):
    img, d = canvas(w, h)
    d.line([0, 36, w, 36], fill=255)
    for i, x in enumerate(range(20, w, 80)):
        d.ellipse([x, 6, x + 16, 22], fill=255)
        d.ellipse([x + 10, 2, x + 26, 18], fill=255)
        d.line([x + 40, 26, x + 36, 36], fill=255, width=2)
        d.line([x + 52, 26, x + 48, 36], fill=255, width=2)
    return img


@orn("tile-dot-grid", "Dot grid tile", "pattern", (16, 16))
def _(w, h):
    img, d = canvas(w, h)
    d.rectangle([7, 7, 8, 8], fill=255)
    return img


@orn("tile-hatch", "Hatch tile", "pattern", (16, 16))
def _(w, h):
    img, d = canvas(w, h)
    d.line([0, 16, 16, 0], fill=255)
    d.line([-8, 8, 8, -8], fill=255)
    d.line([8, 24, 24, 8], fill=255)
    return img


@orn("tile-cross", "Cross tile", "pattern", (16, 16))
def _(w, h):
    img, d = canvas(w, h)
    d.line([8, 6, 8, 10], fill=255)
    d.line([6, 8, 10, 8], fill=255)
    return img


@orn("tile-checker", "Checker tile", "pattern", (16, 16))
def _(w, h):
    img, d = canvas(w, h)
    d.rectangle([0, 0, 7, 7], fill=255)
    d.rectangle([8, 8, 15, 15], fill=255)
    return img


# stamp (96 x 96)
@orn("stamp-round", "Round stamp", "stamp", (96, 96))
def _(w, h):
    img, d = canvas(w, h)
    for a in range(0, 360, 12):
        x = 48 + 44 * math.cos(math.radians(a))
        y = 48 + 44 * math.sin(math.radians(a))
        d.rectangle([x - 1, y - 1, x + 1, y + 1], fill=255)
    d.ellipse([12, 12, 84, 84], outline=255, width=2)
    label_text(d, 22, 40, "PAID")
    return img


# ornament ticket: the ornament applied on a sample section (Inter, 512 wide)
def ornament_ticket(o):
    img, d = canvas(W, SCRATCH_H)
    body = TEXT_FONT
    t = o["type"]
    y = PAD
    if t == "strip":
        img.paste(o["fn"](448, 40), (32, y))
        y += 52
    if t == "pattern":
        tile = o["fn"](16, 16)
        band = Image.new("L", (448, 24), 0)
        for x in range(0, 448, 16):
            band.paste(tile, (x, 4))
        img.paste(band, (32, y))
        y += 34
    if t == "header":
        img.paste(o["fn"](448, 40), (32, y))
        y += 52
    else:
        TEXT_FONT_HEAD.draw(d, PAD, y, "HELLO, YANNIC")
        y += TEXT_FONT_HEAD.cap + 18
    if t == "icon":
        img.paste(o["fn"](48, 48), (W - PAD - 48, PAD))
    if t == "stamp":
        img.paste(o["fn"](96, 96), (W - PAD - 96, PAD))

    body.draw(d, PAD, y, "THREE THINGS FOR TODAY")
    y += body.cap + 16
    if t == "divider":
        img.paste(o["fn"](448, 12), (32, y))
        y += 12 + 14
    else:
        d.line([PAD, y, W - PAD - 1, y], fill=255)
        y += 14

    for i, text in enumerate(["SUNRISE 06:42", "RAIN FROM 15:00", "BINS OUT TONIGHT"]):
        row_y = y + i * 34
        if t == "bullet":
            img.paste(o["fn"](16, 16), (PAD, row_y + 2))
        else:
            d.rectangle([PAD + 2, row_y + 7, PAD + 7, row_y + 12], fill=255)
        body_x = PAD + 28
        TEXT_FONT_ROW.draw(d, body_x, row_y, text)
        d.line([body_x, row_y + 30, W - PAD - 1, row_y + 30], fill=255)
    y += 3 * 34 + 10

    body.draw(d, PAD, y, "UPDATED 07:12")
    y += body.cap + PAD

    if t == "border":
        img2 = img.crop((0, 0, W, y))
        frame = o["fn"](W, y)
        img2 = Image.composite(frame, img2, frame.point(lambda v: 255 if v else 0))
        # the frame draws over content, so this mixes in only the frame's ink
        out = Image.new("L", (W, y), 0)
        out.paste(img.crop((0, 0, W, y)), (0, 0))
        out = Image.blend(out, frame, 0) if False else Image.composite(frame, out, frame)
        img = out
    else:
        img = img.crop((0, 0, W, y))
        d2 = ImageDraw.Draw(img)
        d2.rectangle([8, 8, W - 9, y - 9], outline=255, width=1)
        if t == "corner":
            c = o["fn"](32, 32)
            img.paste(c, (8, 8))
            img.paste(c.transpose(Image.Transpose.FLIP_LEFT_RIGHT), (W - 8 - 32, 8))
            img.paste(c.transpose(Image.Transpose.FLIP_TOP_BOTTOM), (8, y - 8 - 32))
            img.paste(c.transpose(Image.Transpose.ROTATE_180), (W - 8 - 32, y - 8 - 32))
    return to_1bit(img)


TEXT_FONT_HEAD = None
TEXT_FONT_ROW = None


def ornament_standalone(o):
    w, h = o["size"]
    if o["type"] == "border":
        return to_1bit(o["fn"](w, h))
    return to_1bit(o["fn"](w, h))


# ---------- manifest and export ----------

def main():
    global TEXT_FONT, TEXT_FONT_HEAD, TEXT_FONT_ROW
    for sub in ("fonts", "ornaments", "ornament-tickets"):
        (OUT / sub).mkdir(parents=True, exist_ok=True)
    inter = FONT_DIR / "Inter.ttf"
    TEXT_FONT = TTFText(inter, 14)            # caption and small text, cap 14
    TEXT_FONT_ROW = TTFText(inter, 18)        # rows, cap 18
    TEXT_FONT_HEAD = TTFText(inter, 22)       # hello header, cap 22

    manifest = []

    for spec in make_fonts("fonts"):
        fonts = spec["build"](spec["tier"])
        img = font_ticket(fonts, dot=spec["dot"])
        rel = f"fonts/{spec['id']}.png"
        img.save(OUT / rel, optimize=True)
        manifest.append({
            "arena": "fonts", "id": spec["id"], "name": spec["name"], "type": "font",
            "family": spec["family"], "kind": spec["kind"], "size": f"{img.width}x{img.height}",
            "file": f"assets/{rel}", "source": spec["source"], "licence": spec["licence"],
        })
        print("font", spec["id"], img.size)

    for o in ORNAMENTS:
        img = ornament_standalone(o)
        rel = f"ornaments/orn-{o['slug']}.png"
        img.save(OUT / rel, optimize=True)
        ticket = ornament_ticket(o)
        trel = f"ornament-tickets/orn-{o['slug']}.png"
        ticket.save(OUT / trel, optimize=True)
        manifest.append({
            "arena": "ornaments", "id": f"orn-{o['slug']}", "name": o["name"], "type": o["type"],
            "size": f"{img.width}x{img.height}", "file": f"assets/{rel}",
            "ticket": f"assets/{trel}",
            "source": PROJECT, "licence": PROJECT,
        })
        print("ornament", o["slug"], img.size, ticket.size)

    manifest_path = OUT / "manifest.json"
    manifest_path.write_text(json.dumps({
        "generated": "build/build_assets.py",
        "count": len(manifest),
        "assets": manifest,
    }, indent=2), encoding="utf8")
    print("wrote", len(manifest), "assets")


if __name__ == "__main__":
    main()
