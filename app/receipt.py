"""Layout for a receipt ticket.

The layout produces plain lines. The ESC/POS encoder and the text preview both
consume these lines, so what the preview shows matches what the printer prints.
"""

from __future__ import annotations

import base64
import json
import re
import textwrap
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, tzinfo
from typing import Literal

from app.templates import RECIPIENTS, TEMPLATES, Template, template_by_id

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
    # (bytes per row, rows, 1-bit data) for a graphic line. The text is its caption.
    raster: tuple[int, int, bytes] | None = None


def line_to_dict(line: Line) -> dict[str, object]:
    raster = None
    if line.raster is not None:
        width_bytes, height, data = line.raster
        raster = {"width_bytes": width_bytes, "height": height, "data": base64.b64encode(data).decode()}
    return {"text": line.text, "align": line.align, "bold": line.bold, "tall": line.tall, "raster": raster}


def line_from_dict(data: Mapping[str, object]) -> Line:
    raster = None
    if data.get("raster"):
        image = data["raster"]
        raster = (int(image["width_bytes"]), int(image["height"]), base64.b64decode(image["data"]))  # type: ignore[index]
    return Line(
        text=str(data["text"]),
        align=data.get("align", "left"),  # type: ignore[arg-type]
        bold=bool(data.get("bold")),
        tall=bool(data.get("tall")),
        raster=raster,  # type: ignore[arg-type]
    )


@dataclass(frozen=True)
class Receipt:
    recipient: str
    message: str
    sent_at: datetime
    sender: str | None = None
    title: str | None = None


def format_number(value: float) -> str:
    """Whole numbers stay whole, large values get one decimal, small ones keep their digits (0.079 stays 0.079)."""
    if float(value).is_integer():
        return str(int(value))
    if abs(value) >= 10:
        return f"{value:.1f}"
    return f"{value:.3g}"


def sender_label(ticket: Mapping[str, object]) -> str | None:
    """Who the ticket is from: the name of its sender, else the sender label the caller gave."""
    from_user = str(ticket.get("from_user") or "")
    return RECIPIENTS.get(from_user) or (str(ticket["sender"]) if ticket.get("sender") else None)


def receipt_for_ticket(ticket: Mapping[str, object], tz: tzinfo) -> Receipt:
    """Build the receipt content for a stored ticket row."""
    from_user = str(ticket.get("from_user") or "")
    sender = RECIPIENTS.get(from_user) or (str(ticket["sender"]) if ticket["sender"] else None)
    return Receipt(
        recipient=RECIPIENTS.get(str(ticket["recipient"]), str(ticket["recipient"])),
        message=str(ticket["message"]),
        sender=sender,
        title=str(ticket["title"]) if ticket["title"] else None,
        sent_at=datetime.fromtimestamp(int(ticket["send_at_ms"]) / 1000, tz=tz),  # type: ignore[arg-type]
    )


def render_ticket_lines(
    ticket: Mapping[str, object],
    tz: tzinfo,
    width: int = PAPER_WIDTH,
    extra: Sequence[Line] = (),
) -> list[Line]:
    """Lay out a stored ticket using the template and decorations chosen for it.

    `extra` is the live data (Home Assistant values and graphs), fetched just before printing.
    """
    template = template_by_id(int(ticket["template_id"]))  # type: ignore[arg-type]
    if template.design:
        return list(extra)  # the image is the whole ticket; its live lines are the bitmap
    if template.group == "slots":
        from app.compose import ticket_lines  # imported here: app.compose imports app.receipt

        slots = json.loads(str(ticket.get("slots_json") or "{}"))
        return list(extra) or ticket_lines(slots, None, template_id=template.id, sender=sender_label(ticket), recipient=ticket.get("recipient"))
    if ticket.get("kind") == "note":
        from app.compose import note_card_lines  # imported here: app.compose imports app.receipt

        return list(extra) or note_card_lines(str(ticket["message"]), sender_label(ticket), str(ticket["title"]) if ticket["title"] else None)
    # Every other ticket is a message card in the shared shell, so no ticket prints as plain text.
    from app.compose import note_card_lines  # imported here: app.compose imports app.receipt

    title = str(ticket["title"]) if ticket["title"] else None
    return note_card_lines(str(ticket["message"]), sender_label(ticket), title) + list(extra)


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
    extra: Sequence[Line] = (),
) -> list[Line]:
    """Lay out a receipt for paper `width` columns wide, in the given template.

    `extra` lines (data and graphs) go after the message and before the closing rule.
    """
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

    lines += extra
    if "footer" in decorations:
        lines.append(Line("- end -", align="center"))
    else:
        lines.append(rule)
    return lines


def ticket_feed(ticket: Mapping[str, object]) -> int:
    """Lines fed before the cut for this ticket's template."""
    return template_by_id(int(ticket["template_id"])).feed  # type: ignore[arg-type]
