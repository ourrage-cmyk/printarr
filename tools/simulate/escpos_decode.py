"""Decode an ESC/POS byte stream into strips and draw them as PNG, for simulation.

The decoder lives in app/escpos_image.py so the container and the tools draw the same way.

    python tools/simulate/escpos_decode.py stream.bin out.png   # out.png, or out-1.png, out-2.png...
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # so `app` imports when run as a script

from app.escpos_image import Feed, Raster, Strip, Text, decode, render_png  # noqa: E402,F401 (re-exported for hermes_sim)


def main() -> None:
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    strips = decode(src.read_bytes())
    for index, strip in enumerate(strips, 1):
        name = dst if len(strips) == 1 else dst.with_name(f"{dst.stem}-{index}{dst.suffix}")
        render_png(strip, name)
        print(name, "|", "; ".join(strip.summary()))


if __name__ == "__main__":
    main()
