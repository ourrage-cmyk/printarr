"""Composed tickets: an ordered list of typed blocks, drawn as receipt strips.

A block is {type, mood, span, slots}. The types, moods, spans and sizes come from the renderer
(app/render/strips.py and app/render/system/blocks.json), so what is checked here is what gets drawn.
The renderer is pure, so Home Assistant values are read first and filled into the slots. Text that
runs past its card's height is shortened with "..." and reported as a note.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.ha import HAClient, HAError
from app.receipt import Line as ReceiptLine
from app.receipt import format_number
from app.render import strips as R
from app.slots import fetch_values, slot_lines

logger = logging.getLogger("printarr.compose")

MOODS: tuple[str, ...] = tuple(R.MOODS)
AUTO = "auto"  # the decision model picks the mood; the rules pick neutral until it does
MAX_BLOCKS = 16
PLACEHOLDER = "--"  # printed for a value Home Assistant did not give
TICKET_MARGIN = 12  # dots above and below a composed ticket


class BlockProblem(ValueError):
    def __init__(self, problems: list[dict[str, str]]) -> None:
        super().__init__("; ".join(f"{p['slot']}: {p['problem']}" for p in problems))
        self.problems = problems


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class MetricRow(_Strict):
    label: str = Field(min_length=1, max_length=40)
    value: int | float | str | None = Field(default=None, description="The number or text to print.")
    unit: str | None = Field(default=None, max_length=12)
    entity_id: str | None = Field(default=None, max_length=120, description="Home Assistant entity, read at print time.")

    @model_validator(mode="after")
    def _has_value(self) -> MetricRow:
        if self.value is None and self.entity_id is None:
            raise ValueError("send a value (a number or text) or an entity_id (a Home Assistant entity, such as sensor.steps)")
        return self


class MetricSlots(MetricRow):
    series: list[float] | None = Field(default=None, min_length=2, max_length=48, description="Sparkline, oldest first.")


class MetricRowsSlots(_Strict):
    title: str | None = Field(default=None, min_length=1, max_length=40)
    rows: list[MetricRow] = Field(min_length=1, max_length=6)


class GreetingSlots(_Strict):
    greeting: str = Field(min_length=1, max_length=40, description="For example HELLO YANNIC.")
    summary: str | None = Field(default=None, min_length=1, max_length=200)


class GraphSlots(_Strict):
    title: str = Field(min_length=1, max_length=40)
    series: list[float] = Field(min_length=2, max_length=48, description="Values, oldest first.")
    unit: str | None = Field(default=None, max_length=12)


class Dog(_Strict):
    name: str = Field(min_length=1, max_length=20)
    pee: int = Field(default=0, ge=0)
    poop: int = Field(default=0, ge=0)
    food: int = Field(default=0, ge=0)
    run: int = Field(default=0, ge=0)


class DogCountsSlots(_Strict):
    dogs: list[Dog] = Field(min_length=1, max_length=2)


class MessageSlots(_Strict):
    title: str | None = Field(default=None, min_length=1, max_length=40)
    paragraph: str = Field(min_length=1, max_length=800)
    tip: str | None = Field(default=None, min_length=1, max_length=120)
    sign_off: str = Field(alias="from", min_length=1, max_length=20, description="The sign-off, for example Yannic.")


class AlertSlots(_Strict):
    label: str = Field(min_length=1, max_length=40, description="Short, for example WATER LEAK.")
    paragraph: str = Field(min_length=1, max_length=400)
    action: str | None = Field(default=None, min_length=1, max_length=40)


class ChecklistItem(_Strict):
    text: str = Field(min_length=1, max_length=120)
    checked: bool = False


class ChecklistSlots(_Strict):
    title: str | None = Field(default=None, min_length=1, max_length=40)
    items: list[ChecklistItem] = Field(min_length=1, max_length=8)


class TipSlots(_Strict):
    tip: str = Field(min_length=1, max_length=120)


class FactSlots(_Strict):
    paragraph: str = Field(min_length=1, max_length=200)


BLOCKS: dict[str, tuple[type[BaseModel], str]] = {
    "greeting": (GreetingSlots, "A headline at the top of a strip. A greeting always starts a new strip."),
    "metric": (MetricSlots, "One number shown large, with an optional sparkline."),
    "metric_rows": (MetricRowsSlots, "Up to six labelled values, with dot leaders."),
    "graph": (GraphSlots, "A line graph over a series of values."),
    "dog_counts": (DogCountsSlots, "Counts for one or two dogs: pee, poop, food and run."),
    "message": (MessageSlots, "A message from one person, with an optional tip and sign-off."),
    "alert": (AlertSlots, "A heads-up with a filled label, a paragraph and an optional action."),
    "checklist": (ChecklistSlots, "A list with a box or a tick per item."),
    "tip": (TipSlots, "One line of advice."),
    "fact": (FactSlots, "A short fun fact."),
}


def _span_info(name: str) -> dict[str, Any]:
    lay = R.LAYOUT[name]
    return {
        "default": lay["span"],
        "min": lay["min_span"],
        "max": 3,
        "description": "Columns the block takes: 1, 2 or 3. Blocks sit side by side when they fit.",
    }


def _units_info(name: str) -> dict[str, int]:
    lay = R.LAYOUT[name]
    return {"min": lay["min_units"], "max": lay["max_units"]}


def catalogue() -> list[dict[str, Any]]:
    return [
        {
            "type": name,
            "description": text,
            "span": _span_info(name),
            "units": _units_info(name),
            "moods": list(MOODS) + [AUTO],
            "schema": f"/api/v1/blocks/{name}/schema",
        }
        for name, (_, text) in BLOCKS.items()
    ]


def block_schema(name: str) -> dict[str, Any]:
    model, text = BLOCKS[name]
    return {
        **model.model_json_schema(),
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": name,
        "description": text,
        "span": _span_info(name),
        "units": _units_info(name),
    }


def plain_message(message: str) -> str:
    """A validation message without Pydantic's wording."""
    return message.removeprefix("Value error, ")


def _slot_problems(where: str, exc: ValidationError) -> list[dict[str, str]]:
    problems = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"]) or "slots"
        problems.append({"slot": f"{where}.slots.{location}", "problem": plain_message(error["msg"])})
    return problems


def validate_blocks(raw_blocks: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Check every block. Raises BlockProblem naming each wrong slot as blocks[i].slots.x."""
    problems: list[dict[str, str]] = []
    checked: list[dict[str, Any]] = []
    if not 1 <= len(raw_blocks) <= MAX_BLOCKS:
        problems.append({"slot": "blocks", "problem": f"give 1 to {MAX_BLOCKS} blocks"})
    for index, raw in enumerate(raw_blocks):
        name = raw.get("type")
        mood = raw.get("mood")
        where = f"blocks[{index}]"
        if name not in BLOCKS:
            problems.append({"slot": f"{where}.type", "problem": f"unknown block type {name!r}"})
            continue
        if mood not in MOODS and mood != AUTO:
            problems.append({"slot": f"{where}.mood", "problem": f"mood must be one of {', '.join(MOODS)} or auto"})
            continue
        lay = R.LAYOUT[name]
        span = raw.get("span") if raw.get("span") is not None else lay["span"]
        if span not in (1, 2, 3) or span < lay["min_span"]:
            problems.append({"slot": f"{where}.span", "problem": f"{name} takes {lay['min_span']} to 3 columns"})
            continue
        try:
            slots = BLOCKS[name][0].model_validate(dict(raw.get("slots") or {}))
        except ValidationError as exc:
            problems.extend(_slot_problems(where, exc))
            continue
        checked.append({
            "type": name,
            "mood": "neutral" if mood == AUTO else mood,  # the decision model replaces this later
            "span": span,
            "slots": slots.model_dump(by_alias=True, exclude_none=True),
        })
    if problems:
        raise BlockProblem(problems)
    return checked


def entity_ids(blocks: Sequence[Mapping[str, Any]]) -> list[str]:
    found: list[str] = []
    for block in blocks:
        slots = block.get("slots", {})
        for item in [slots, *slots.get("rows", [])]:
            entity = item.get("entity_id")
            if entity and entity not in found:
                found.append(entity)
    return found


def fetch_entities(blocks: Sequence[Mapping[str, Any]], client: HAClient | None) -> dict[str, str | None]:
    values: dict[str, str | None] = {}
    for entity in entity_ids(blocks):
        if client is None:
            values[entity] = None
            continue
        try:
            number = float(client.state(entity))
            values[entity] = format_number(number)
        except (HAError, ValueError, TypeError) as exc:
            logger.warning("entity %s unavailable: %s", entity, exc)
            values[entity] = None
    return values


def _filled_row(row: Mapping[str, Any], values: Mapping[str, str | None]) -> dict[str, Any]:
    if row.get("value") is None and row.get("entity_id"):
        return {**row, "value": values.get(row["entity_id"]) or PLACEHOLDER}
    return dict(row)


def fill_values(blocks: Sequence[Mapping[str, Any]], values: Mapping[str, str | None]) -> list[dict[str, Any]]:
    """Copies the blocks with each entity-backed value replaced by what Home Assistant gave."""
    filled = []
    for block in blocks:
        slots = dict(block["slots"])
        if block["type"] == "metric":
            slots = _filled_row(slots, values)
        if block["type"] == "metric_rows":
            slots["rows"] = [_filled_row(row, values) for row in slots.get("rows", [])]
        filled.append({**block, "slots": slots})
    return filled


def _render_blocks(blocks: Sequence[Mapping[str, Any]]) -> list[R.Block]:
    return [
        R.Block(
            type=block["type"],
            slots=block["slots"],
            mood=block.get("mood", R.NEUTRAL),
            span=block.get("span") or R.LAYOUT[block["type"]]["span"],
        )
        for block in blocks
    ]


def compose_render(blocks: Sequence[Mapping[str, Any]], client: HAClient | None) -> tuple[list[ReceiptLine], list[str]]:
    """Draws a composed ticket: one raster line per strip, plus the notes for any text that was shortened."""
    filled = fill_values(blocks, fetch_entities(blocks, client))
    lines: list[ReceiptLine] = []
    notes: list[str] = []
    for strip in R.split_strips(_render_blocks(filled)):
        bitmap, strip_notes = R.render_strip_with_notes(strip, margin_top=TICKET_MARGIN, margin_bottom=TICKET_MARGIN)
        lines.append(ReceiptLine("", raster=(bitmap.width // 8, bitmap.height, bitmap.bits)))
        notes.extend(strip_notes)
    return lines, notes


def summary(blocks: Sequence[Mapping[str, Any]]) -> str:
    """A short label for the ticket's log row, taken from its first block."""
    first = blocks[0]["slots"]
    for key in ("greeting", "label", "paragraph", "title", "tip"):
        if first.get(key):
            return str(first[key])
    return "(composed)"


def ticket_lines(slots: Mapping[str, Any], client: HAClient | None) -> list[ReceiptLine]:
    """Lay out any stored slot ticket: a composed one, or a slot template (briefing and note)."""
    if "blocks" in slots:
        lines, _ = compose_render(slots["blocks"], client)
        return lines
    return slot_lines(slots, fetch_values(slots, client))
