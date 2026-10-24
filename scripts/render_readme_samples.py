"""Writes the sample strip PNGs used in README.md, drawn by the app's own strip renderer.

Usage (from the repository root, with Pillow installed: pip install pillow):
    python scripts/render_readme_samples.py

The sample blocks come from scripts/strip_demo.py. Nothing is sent to a printer or simulator.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from app.render.strips import render_strip  # noqa: E402
import strip_demo  # noqa: E402

OUT = ROOT / "docs" / "images"
SAMPLES = {
    "strip-morning-briefing.png": strip_demo.STRIPS["morning-briefing-1"],
    "strip-evening-rundown.png": strip_demo.STRIPS["evening-rundown"],
    "strip-shopping-list.png": strip_demo.STRIPS["shopping"],
    "strip-alert.png": strip_demo.STRIPS["alert-urgent"],
}


def to_png(bitmap, path: Path) -> None:
    """Bit 1 is black, rows are MSB first, as the printer receives them."""
    image = Image.new("1", (bitmap.width, bitmap.height), 1)
    pixels = image.load()
    row_bytes = bitmap.width // 8
    for y in range(bitmap.height):
        for x in range(bitmap.width):
            if bitmap.bits[y * row_bytes + (x >> 3)] & (0x80 >> (x & 7)):
                pixels[x, y] = 0
    image.save(path, optimize=True)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, blocks in SAMPLES.items():
        bitmap = render_strip(blocks)
        to_png(bitmap, OUT / name)
        print(f"{OUT / name} {bitmap.width}x{bitmap.height}")


if __name__ == "__main__":
    main()
