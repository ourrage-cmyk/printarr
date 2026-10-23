"""Layout for a receipt ticket.

The layout produces plain lines. The ESC/POS encoder and the text preview both
consume these lines, so what the preview shows matches what the printer prints.
"""

from __future__ import annotations

import re
import textwrap
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, tzinfo
from typing import Literal

from app.templates import TEMPLATES, Template, template_by_id

Align = Literal["left", "center"]

# TM-T88V on 80 mm paper: 512 printable dots, Font A is 12 dots wide, so 42 columns.
# Epson TRG, "Characters per line". Override with PRINTARR_PAPER_WIDTH after verification.
PAPER_WIDTH = 42

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
    """Build the receipt content for a stored ticket row."""
    return Receipt(
        recipient=str(ticket["recipient"]),
        message=str(ticket["message"]),
        sender=str(ticket["sender"]) if ticket["sender"] else None,
        title=str(ticket["title"]) if ticket["title"] else None,
        sent_at=datetime.fromtimestamp(int(ticket["send_at_ms"]) / 1000, tz=tz),  # type: ignore[arg-type]
    )


def render_ticket_lines(ticket: Mapping[str, object], tz: tzinfo, width: int = PAPER_WIDTH) -> list[Line]:
    """Lay out a stored ticket using the template and decorations chosen for it."""
    template = template_by_id(int(ticket["template_id"]))  # type: ignore[arg-type]
    decorations = tuple(d for d in str(ticket["decorations"] or "").split(",") if d)
    return render_lines(receipt_for_ticket(ticket, tz), width, template, decorations)


def wrap(text: str, width: int) -> list[str]:
    """Word-wrap text to the given width, keeping the sender's own line breaks."""
    text = _CONTROL_CHARS.sub("", text.replace("\t", "    ").replace("\r", ""))
    rows: list[str] = []
    for paragraph in text.split("\n"):
        wrapped = textwrap.wrap(
            paragraph, width=width, break_long_words=True, break_on_hyphens=False
        )
        rows.extend(wrapped or [""])
    return rows


def render_lines(
    receipt: Receipt,
    width: int = PAPER_WIDTH,
    template: Template = TEMPLATES[0],
    decorations: tuple[str, ...] = (),
) -> list[Line]:
    """Lay out a receipt for paper `width` columns wide, in the given template."""
    rule = Line(template.rule * width)
    body_width = width - 4 if "frame" in decorations else width
    lines = [
        Line(receipt.sent_at.strftime("%a %d %b %Y  %H:%M"), align="center"),
        rule,
        *(Line(row, bold=True) for row in wrap(f"TO: {receipt.recipient}", width)),
    ]
    if receipt.sender:
        lines += [Line(row, bold=True) for row in wrap(f"FROM: {receipt.sender}", width)]
    lines.append(rule)

    star_rule = Line("*" * width, align="center")
    if receipt.title:
        if "stars" in decorations:
            lines.append(star_rule)
        lines += [
            Line(row, align=template.title_align, bold=True, tall=template.tall_title)
            for row in wrap(receipt.title, width)
        ]
        if "stars" in decorations:
            lines.append(star_rule)
        lines.append(Line(""))

    message = wrap(receipt.message, body_width)
    if "frame" in decorations:
        border = Line("+" + "-" * (width - 2) + "+")
        lines.append(border)
        lines += [Line(f"| {row.ljust(body_width)} |") for row in message]
        lines.append(border)
    else:
        lines += [Line(row) for row in message]

    if "footer" in decorations:
        lines.append(Line("- end -", align="center"))
    else:
        lines.append(rule)
    return lines
