"""Graphic and data blocks for a ticket. Values come from Home Assistant at request time,
and the result is stored on the ticket, so printing needs no network call."""

from __future__ import annotations

import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from app.ha import HAClient, HAError
from app.receipt import Line

ENTITY_PATTERN = r"^[a-z_]+\.[a-z0-9_]+$"
GRAPH_WIDTH = 512  # printable dots on the TM-T88V
GRAPH_HEIGHT = 64


class ValueBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["value"]
    entity_id: str = Field(pattern=ENTITY_PATTERN, examples=["sensor.living_room_temperature"])
    label: str = Field(min_length=1, max_length=40)
    unit: str | None = Field(default=None, max_length=12)


class SparklineBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["sparkline"]
    entity_id: str = Field(pattern=ENTITY_PATTERN)
    label: str = Field(min_length=1, max_length=40)
    hours: int = Field(default=24, ge=1, le=168)


Block = Annotated[ValueBlock | SparklineBlock, Field(discriminator="type")]


def _set(rows: list[bytearray], x: int, y: int) -> None:
    if 0 <= x < GRAPH_WIDTH and 0 <= y < GRAPH_HEIGHT:
        rows[y][x >> 3] |= 0x80 >> (x & 7)


def _line(rows: list[bytearray], x0: int, y0: int, x1: int, y1: int) -> None:
    """Bresenham line, so a connected graph has no gaps."""
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    err = dx + dy
    while True:
        _set(rows, x0, y0)
        if x0 == x1 and y0 == y1:
            return
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


def sparkline_bitmap(values: list[float]) -> bytes:
    """1-bit bitmap, row by row, MSB first, bit 1 = black. Size GRAPH_WIDTH x GRAPH_HEIGHT."""
    if len(values) < 2:
        raise HAError("not enough numeric history for a graph")
    rows = [bytearray(GRAPH_WIDTH // 8) for _ in range(GRAPH_HEIGHT)]
    for x in range(0, GRAPH_WIDTH, 4):  # dotted baseline
        _set(rows, x, GRAPH_HEIGHT - 1)
    low, high = min(values), max(values)
    span = (high - low) or 1.0
    points = []
    for index, value in enumerate(values):
        x = round(index * (GRAPH_WIDTH - 1) / (len(values) - 1))
        y = round((GRAPH_HEIGHT - 2) - (value - low) / span * (GRAPH_HEIGHT - 3))
        points.append((x, y))
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        _line(rows, x0, y0, x1, y1)
    return bytes(byte for row in rows for byte in row)


def _format(value: str, unit: str | None) -> str:
    return f"{value} {unit}" if unit else value


def resolve_blocks(blocks: list[Block], client: HAClient | None) -> list[Line]:
    """Fetch every block's data now. Any Home Assistant failure raises HAError."""
    if blocks and client is None:
        raise HAError("Home Assistant is not configured; set its URL and token in the web page")
    lines: list[Line] = []
    for block in blocks:
        assert client is not None
        if isinstance(block, ValueBlock):
            state = client.state(block.entity_id)
            shown = state if state not in ("unavailable", "unknown") else "no data"
            lines.append(Line(f"{block.label}: {_format(shown, block.unit)}"))
        else:
            values = client.numeric_history(block.entity_id, block.hours)
            if len(values) < 2:
                raise HAError(f"{block.entity_id} has no numeric history for {block.hours} h")
            lines.append(Line(f"{block.label} ({block.hours} h, now {values[-1]:g})", align="center"))
            lines.append(Line("", raster=(GRAPH_WIDTH // 8, GRAPH_HEIGHT, sparkline_bitmap(values))))
    return lines


_BLOCK_LIST = TypeAdapter(list[Block])


def parse_blocks(text: str | None) -> list[Block]:
    """Block definitions stored on a ticket, read back for printing."""
    return _BLOCK_LIST.validate_python(json.loads(text or "[]"))


def unavailable_lines(blocks: list[Block]) -> list[Line]:
    """What prints in place of live data when Home Assistant cannot be reached at print time."""
    return [Line(f"{block.label}: data unavailable") for block in blocks]
