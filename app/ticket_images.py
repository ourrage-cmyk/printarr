"""A PNG of every ticket as it was sent to the printer, kept so a bad print can be looked at later.

Files are <db folder>/tickets/images/<ticket id>.png. Only the newest `keep` files are kept: after each
save, older images are deleted. Printing never waits on this, and a failure here is logged, not raised.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

TICKET_ID = re.compile(r"[0-9a-f]{32}")


def image_path(images_dir: Path, ticket_id: str) -> Path | None:
    """The file for a ticket id, or None when the id is not one printarr makes (no path tricks)."""
    if not TICKET_ID.fullmatch(ticket_id):
        return None
    return images_dir / f"{ticket_id}.png"


def save(images_dir: Path, ticket_id: str, png: bytes, keep: int) -> Path:
    """Write the image atomically, then delete everything older than the newest `keep`."""
    images_dir.mkdir(parents=True, exist_ok=True)
    path = images_dir / f"{ticket_id}.png"
    tmp = images_dir / f"{ticket_id}.tmp"
    tmp.write_bytes(png)
    os.replace(tmp, path)
    prune(images_dir, keep)
    return path


def recent(images_dir: Path, limit: int) -> list[str]:
    """Ticket ids that have an image, newest first."""
    return [path.stem for path in _newest_first(images_dir)[:limit]]


def prune(images_dir: Path, keep: int) -> list[str]:
    """Delete all but the newest `keep` images. Returns the ids removed."""
    removed = []
    for path in _newest_first(images_dir)[max(keep, 0):]:
        path.unlink(missing_ok=True)
        removed.append(path.stem)
    return removed


def _newest_first(images_dir: Path) -> list[Path]:
    if not images_dir.is_dir():
        return []
    files = []
    for path in images_dir.glob("*.png"):
        try:
            files.append((path.stat().st_mtime_ns, path.name, path))
        except FileNotFoundError:  # removed between the listing and the stat
            continue
    files.sort(reverse=True)
    return [path for _, _, path in files]
