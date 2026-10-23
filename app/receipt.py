"""Layout for a receipt ticket.

The layout produces plain lines. The ESC/POS encoder and the text preview both
consume these lines, so what the web preview shows matches what the printer prints.
"""

from __future__ import annotations

import re
import textwrap
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, tzinfo
from typing import Literal

Align = Literal["left", "center"]

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


@dataclass(frozen=True)
class Line:
    text: str
    align: Align = "left"
    bold: bool = False
    tall: bool = False


@dataclass(frozen=True)
class Receipt:
    recipient: str
    message: str
    sent_at: datetime
    sender: str | None = None
    title: str | None = None


def receipt_for_ticket(ticket: Mapping[str, object], tz: tzinfo) -> Receipt:
    """Build the receipt for a stored ticket row."""
    return Receipt(
        recipient=str(ticket["recipient"]),
        message=str(ticket["message"]),
        sender=ticket["sender"] if ticket["sender"] else None,  # type: ignore[arg-type]
        title=ticket["title"] if ticket["title"] else None,  # type: ignore[arg-type]
        sent_at=datetime.fromtimestamp(int(ticket["send_at_ms"]) / 1000, tz=tz),  # type: ignore[arg-type]
    )


def wrap(text: str, width: int) -> list[str]:
    """Word-wrap text to the paper width, keeping the sender's own line breaks."""
    text = _CONTROL_CHARS.sub("", text.replace("\t", "    ").replace("\r", ""))
    rows: list[str] = []
    for paragraph in text.split("\n"):
        wrapped = textwrap.wrap(
            paragraph, width=width, break_long_words=True, break_on_hyphens=False
        )
        rows.extend(wrapped or [""])
    return rows


def render_lines(receipt: Receipt, width: int = 48) -> list[Line]:
    """Lay out a receipt for a paper that is `width` characters wide (Font A)."""
    rule = Line("-" * width)
    lines = [
        Line(receipt.sent_at.strftime("%a %d %b %Y  %H:%M"), align="center"),
        rule,
        *(Line(row, bold=True) for row in wrap(f"TO: {receipt.recipient}", width)),
    ]
    if receipt.sender:
        lines += [Line(row, bold=True) for row in wrap(f"FROM: {receipt.sender}", width)]
    lines.append(rule)
    if receipt.title:
        lines += [
            Line(row, align="center", bold=True, tall=True)
            for row in wrap(receipt.title, width)
        ]
        lines.append(Line(""))
    lines += [Line(row) for row in wrap(receipt.message, width)]
    lines.append(rule)
    return lines
