"""Contact sheets: every kind, mood and block drawn side by side, so cohesion is visible at a glance.

    python tools/contact_sheet.py OUT_DIR

Writes one PNG per sheet into OUT_DIR. Each cell is one ticket drawn by the same renderer the
printer gets (app/render/strips.py and app/render/designs.py), at paper width, so margins, type
roles and card styling are compared exactly as they will print. Look at the sheets, then fix what
differs. The cell labels name the block, mood or design.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.render import strips  # noqa: E402
from app.render.canvas import PAPER_DOTS, ROW_BYTES, Bitmap  # noqa: E402
from app.render.designs import Morning, morning_system  # noqa: E402
from app.render.strips import Block  # noqa: E402

CELL_GAP = 24
LABEL_H = 22
SHEET_COLUMNS = 4


def to_image(bitmap: Bitmap) -> Image.Image:
    """1-bit bitmap to an image: ink is black on white paper."""
    image = Image.new("1", (PAPER_DOTS, bitmap.height), 1)
    pixels = image.load()
    for y in range(bitmap.height):
        row = bitmap.bits[y * ROW_BYTES : (y + 1) * ROW_BYTES]
        for x in range(PAPER_DOTS):
            if row[x >> 3] & (0x80 >> (x & 7)):
                pixels[x, y] = 0
    return image.convert("L")


def samples() -> list[tuple[str, Bitmap]]:
    """One ticket per block type in its neutral mood, then every mood on a metric and a message."""
    cells: list[tuple[str, Bitmap]] = []
    block_samples = {
        "greeting": {"greeting": "Good morning, Yannic", "summary": "Cloudy, 12 C. Bins out tonight."},
        "metric": {"label": "Body battery", "value": 74, "unit": "%", "series": [40, 52, 61, 58, 70, 74]},
        "metric_rows": {"title": "Home now", "rows": [{"label": "Power", "value": 0.42, "unit": "kWh"}, {"label": "Rate", "value": 27, "unit": "p"}]},
        "graph": {"title": "Living room", "series": [18, 19, 21, 20, 22, 21.5], "unit": "C"},
        "dog_counts": {"dogs": [{"name": "Milo", "pee": 3, "poop": 1, "food": 2, "run": 1}, {"name": "Bea", "pee": 2, "poop": 0, "food": 2, "run": 0}]},
        "message": {"title": "Parcel", "paragraph": "Parcel is at the back door. Please bring it in before the rain.", "from": "Yannic"},
        "alert": {"label": "WATER LEAK", "paragraph": "Kitchen sensor is wet. Check under the sink.", "action": "Turn off the tap"},
        "checklist": {"title": "Shopping", "items": [{"text": "Milk", "checked": False}, {"text": "Bread", "checked": True}]},
        "tip": {"tip": "Leave ten minutes early when it rains."},
        "fact": {"paragraph": "A dot matrix head prints one row at a time."},
    }
    for name, slots in block_samples.items():
        try:
            cells.append((f"block:{name}", strips.render_strip([Block(name, slots)])))
        except (KeyError, ValueError) as exc:  # a sample that no longer matches the catalogue is reported, not hidden
            cells.append((f"block:{name} ERROR {exc}", _blank()))
    for mood in strips.MOODS:
        cells.append((f"mood:{mood}", strips.render_strip([Block("message", block_samples["alert"], mood=mood)])))
    cells.append(("design:morning", morning_system(Morning(summary="Good morning, Yannic.", body_battery=74, stress=21, steps=6120, cpu=18, ram=63))))
    cells.append(("design:morning NO DATA", morning_system(Morning(summary="Good morning.", body_battery=None, stress=None, steps=None, cpu=None, ram=None))))
    return cells


def _blank() -> Bitmap:
    return Bitmap(PAPER_DOTS, 8, bytes(ROW_BYTES * 8))


def sheet(cells: list[tuple[str, Bitmap]], title: str) -> Image.Image:
    images = [(label, to_image(bitmap)) for label, bitmap in cells]
    cell_w = PAPER_DOTS
    rows = [images[i : i + SHEET_COLUMNS] for i in range(0, len(images), SHEET_COLUMNS)]
    row_heights = [max(img.height for _, img in row) + LABEL_H for row in rows]
    width = SHEET_COLUMNS * cell_w + (SHEET_COLUMNS + 1) * CELL_GAP
    height = sum(row_heights) + (len(rows) + 1) * CELL_GAP + LABEL_H
    out = Image.new("L", (width, height), 200)
    draw = ImageDraw.Draw(out)
    draw.text((CELL_GAP, 4), title, fill=0)
    y = LABEL_H + CELL_GAP
    for row, row_h in zip(rows, row_heights):
        for col, (label, img) in enumerate(row):
            x = CELL_GAP + col * (cell_w + CELL_GAP)
            draw.text((x, y), label, fill=0)
            out.paste(img, (x, y + LABEL_H))
        y += row_h + CELL_GAP
    return out


def main(out_dir: str) -> None:
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    cells = samples()
    per_sheet = 12
    for index in range(0, len(cells), per_sheet):
        part = cells[index : index + per_sheet]
        name = f"contact-sheet-{index // per_sheet + 1:02d}.png"
        sheet(part, f"printarr contact sheet {index // per_sheet + 1}").save(target / name)
        print(target / name)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "contact-sheets")
