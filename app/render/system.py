"""Receipt design system: tokens, ornament pieces and which piece sits on which card.

The data lives in app/render/system/, copied from docs/design/system/tokens.json and
design-lab/system/assets/. Ornament duels are settled by editing decorations.json, not code.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from PIL import Image

from app.render.canvas import Mark

DATA = Path(__file__).parent / "system"


@lru_cache(maxsize=1)
def tokens() -> dict:
    return json.loads((DATA / "tokens.json").read_text())


@lru_cache(maxsize=1)
def pieces() -> dict[str, dict]:
    """Ornament pieces from the manifest, keyed by id."""
    manifest = json.loads((DATA / "manifest.json").read_text())
    return {a["id"]: a for a in manifest["assets"] if a["arena"] == "pieces"}


@lru_cache(maxsize=1)
def decorations() -> dict[str, dict[str, str]]:
    """design id -> card name -> piece id."""
    return json.loads((DATA / "decorations.json").read_text())


def card_radius() -> int:
    return int(tokens()["radius"]["card"])


def spacing(name: str) -> int:
    return int(tokens()["grid"]["spacing"][name])


@lru_cache(maxsize=None)
def ornament(piece_id: str) -> Mark:
    """Load one piece as the ink pixels of a 1-bit PNG (black ink = 0 in the file)."""
    asset = pieces()[piece_id]
    if asset["type"] != "icon":
        raise NotImplementedError(f"piece type {asset['type']!r} has no placement yet ({piece_id})")
    with Image.open(DATA / asset["file"]) as image:
        image = image.convert("1")
        width, height = image.size
        pixels = image.load()
        ink = tuple((x, y) for y in range(height) for x in range(width) if pixels[x, y] == 0)
    return Mark(width, height, ink)
