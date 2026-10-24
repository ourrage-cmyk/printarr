"""Turns an ESC/POS byte stream back into a picture of what the printer was sent.

Used to keep a PNG of every ticket (app/ticket_images.py) and by the simulator tools.

Understands what printarr sends: ESC @, ESC a, ESC E, ESC t, ESC d, GS !, GS V, text lines,
GS ( L raster (function 112, and fn 50 print) and the obsolete GS v 0 raster. Each partial
cut ends a strip.

Raster rows are drawn as the printer receives them, one dot per pixel on a 512-dot paper, so
images, dot matrix titles and charts are exact. Text lines are drawn with a font as an
approximation of Font A (12 x 24 dots): the real simulator on the laptop is the reference for text.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PAPER_DOTS = 512
LINE_DOTS = 24  # Font A line height in dots
FONT_PATH = Path(__file__).parent / "fonts" / "NotoSans-Regular.ttf"  # shipped with the app, so the image works in the container


@dataclass
class Text:
    text: str
    align: str
    bold: bool
    tall: bool


@dataclass
class Raster:
    align: str
    width: int  # dots
    rows: list[bytes]


@dataclass
class Feed:
    lines: int


@dataclass
class Strip:
    items: list[Text | Raster | Feed] = field(default_factory=list)

    def summary(self) -> list[str]:
        out = []
        for item in self.items:
            if isinstance(item, Text):
                out.append(f"text: {item.text.strip()[:40]}")
            elif isinstance(item, Raster):
                out.append(f"raster {item.width}x{len(item.rows)}")
        return out


def _u16(lo: int, hi: int) -> int:
    return lo + hi * 256


def decode(stream: bytes) -> list[Strip]:
    """Split the stream into strips. A strip ends at each partial cut."""
    strips: list[Strip] = []
    current = Strip()
    align, bold, tall = "left", False, False
    line = bytearray()
    i, n = 0, len(stream)

    def end_line() -> None:
        if line:
            current.items.append(Text(line.decode("cp437", errors="replace"), align, bold, tall))
            line.clear()

    while i < n:
        b = stream[i]
        if b == 0x1B and i + 1 < n:  # ESC
            c = stream[i + 1]
            if c == 0x40:  # ESC @ initialise
                align, bold, tall = "left", False, False
                i += 2
            elif c == 0x61 and i + 2 < n:  # ESC a n: justification
                align = {0: "left", 1: "center", 2: "right"}.get(stream[i + 2], "left")
                i += 3
            elif c == 0x45 and i + 2 < n:  # ESC E n: bold
                bold = bool(stream[i + 2] & 1)
                i += 3
            elif c == 0x64 and i + 2 < n:  # ESC d n: feed n lines
                end_line()
                current.items.append(Feed(stream[i + 2]))
                i += 3
            else:  # ESC t n and other one-parameter commands
                i += 3
            continue
        if b == 0x1D and i + 1 < n:  # GS
            c = stream[i + 1]
            if c == 0x21 and i + 2 < n:  # GS ! n: character size, bit 0 = double height
                tall = bool(stream[i + 2] & 0x01)
                i += 3
            elif c == 0x56 and i + 2 < n:  # GS V m: partial cut ends the strip
                end_line()
                strips.append(current)
                current = Strip()
                i += 4 if stream[i + 2] in (65, 66) else 3
            elif c == 0x28 and i + 4 < n and stream[i + 2] == 0x4C:  # GS ( L pL pH fn ...
                length = _u16(stream[i + 3], stream[i + 4])
                body = stream[i + 5 : i + 5 + length]
                if len(body) >= 10 and body[1] == 112:  # fn 112: raster image
                    width = _u16(body[6], body[7])
                    height = _u16(body[8], body[9])
                    row_bytes = (width + 7) // 8
                    data = body[10 : 10 + row_bytes * height]
                    end_line()
                    rows = [data[y * row_bytes : (y + 1) * row_bytes] for y in range(height)]
                    current.items.append(Raster(align, width, rows))
                i += 5 + length
            elif c == 0x76 and i + 7 < n and stream[i + 2] == 0x30:  # GS v 0 m xL xH yL yH: obsolete raster
                row_bytes = _u16(stream[i + 4], stream[i + 5])
                height = _u16(stream[i + 6], stream[i + 7])
                end_line()
                data = stream[i + 8 : i + 8 + row_bytes * height]
                rows = [data[y * row_bytes : (y + 1) * row_bytes] for y in range(height)]
                current.items.append(Raster(align, row_bytes * 8, rows))
                i += 8 + row_bytes * height
            else:
                i += 2
            continue
        if b == 0x0A:  # LF ends a text line
            end_line()
            i += 1
            continue
        line.append(b)
        i += 1
    end_line()
    if current.items:
        strips.append(current)
    return strips


def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_PATH), size)


def _x_for(align: str, width: int) -> int:
    return {"left": 0, "center": (PAPER_DOTS - width) // 2, "right": PAPER_DOTS - width}.get(align, 0)


def render_png(strip: Strip, path: Path, margin: int = 12) -> None:
    """Draw one strip to a PNG file: 1 dot = 1 pixel, ink black on white paper."""
    Path(path).write_bytes(render_png_bytes(strip, margin))


def render_png_bytes(strip: Strip, margin: int = 12) -> bytes:
    """Draw one strip to PNG bytes."""
    height = margin * 2
    for item in strip.items:
        if isinstance(item, Text):
            height += LINE_DOTS * (2 if item.tall else 1)
        elif isinstance(item, Raster):
            height += len(item.rows)
        else:
            height += LINE_DOTS * item.lines // 2
    img = Image.new("L", (PAPER_DOTS, max(height, 2 * margin)), 255)
    draw = ImageDraw.Draw(img)
    y = margin
    for item in strip.items:
        if isinstance(item, Text):
            scale = 2 if item.tall else 1
            font = _font(20 * scale)
            x0 = _x_for(item.align, 12 * scale * len(item.text))
            for k, ch in enumerate(item.text):
                x = x0 + k * 12 * scale
                draw.text((x, y), ch, fill=0, font=font)
                if item.bold:
                    draw.text((x + 1, y), ch, fill=0, font=font)
            y += LINE_DOTS * scale
        elif isinstance(item, Raster):
            x0 = _x_for(item.align, item.width)
            for row in item.rows:
                for x_byte, byte in enumerate(row):
                    for bit in range(8):
                        if byte & (0x80 >> bit) and 0 <= x0 + x_byte * 8 + bit < PAPER_DOTS:
                            img.putpixel((x0 + x_byte * 8 + bit, y), 0)
                y += 1
        else:
            y += LINE_DOTS * item.lines // 2
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def payload_to_png(stream: bytes, margin: int = 12) -> bytes:
    """Every strip in the stream as one PNG. A stream without a cut is one strip."""
    merged = Strip()
    for strip in decode(stream):
        merged.items.extend(strip.items)
    if not merged.items:
        raise ValueError("the stream has nothing to draw")
    return render_png_bytes(merged, margin)
