"""Composed tickets: an ordered list of typed blocks on one shared card shell.

A block is {type, mood, slots}. The catalogue below is the first draft from the template thread's
summary. Mood changes only the look of a block (ornament, icon, accent), never its size, so blocks
stack without re-layout. The text layout here is a fallback until the renderer lands.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.ha import HAClient, HAError
from app.receipt import Line, wrap
from app.slots import PAPER_WIDTH, Metric, fetch_values, slot_lines

logger = logging.getLogger("printarr.compose")

MOODS: tuple[str, ...] = (
    "happy", "sad", "confused", "excited", "upset", "factual", "reminder",
    "loving", "playful", "gentle", "firm", "urgent", "neutral",
)
AUTO = "auto"  # the decision model picks the mood; the rules pick neutral until it does
MAX_BLOCKS = 16


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TextSlots(_Strict):
    text: str = Field(min_length=1, max_length=400)


class TitleSlots(_Strict):
    text: str = Field(min_length=1, max_length=60)


class GreetingSlots(_Strict):
    text: str = Field(min_length=1, max_length=40)


class TipSlots(_Strict):
    text: str = Field(min_length=1, max_length=120)


class MessageSlots(_Strict):
    text: str = Field(min_length=1, max_length=400)
    from_name: str = Field(min_length=1, max_length=20, description="The sign-off, for example Yannic.")


class MetricTilesSlots(_Strict):
    metrics: list[Metric] = Field(min_length=1, max_length=2)


class MetricRowsSlots(_Strict):
    metrics: list[Metric] = Field(min_length=1, max_length=6)


class GraphSlots(_Strict):
    metric: Metric


class DogCountsSlots(_Strict):
    label: str = Field(min_length=1, max_length=20)
    items: list[dict[str, Any]] = Field(min_length=1, max_length=6, description="Each {label, count}.")


class ListSlots(_Strict):
    title: str | None = Field(default=None, max_length=40)
    items: list[str] = Field(min_length=1, max_length=10)


class TodoSlots(_Strict):
    title: str | None = Field(default=None, max_length=40)
    items: list[dict[str, Any]] = Field(min_length=1, max_length=10, description="Each {text, done}.")


class AlertSlots(_Strict):
    text: str = Field(min_length=1, max_length=120)
    level: str = Field(default="info", pattern="^(info|warning|urgent)$")


class FunFactSlots(_Strict):
    text: str = Field(min_length=1, max_length=200)


BLOCKS: dict[str, tuple[type[BaseModel], str]] = {
    "greeting": (GreetingSlots, "A line at the top, such as Good morning, Yannic."),
    "title": (TitleSlots, "A heading."),
    "paragraph": (TextSlots, "A paragraph of text."),
    "message": (MessageSlots, "A message from one person, signed off."),
    "tip": (TipSlots, "A closing tip or reminder."),
    "metric_tiles": (MetricTilesSlots, "One or two numbers, each shown large."),
    "metric_rows": (MetricRowsSlots, "Up to six numbers as label rows."),
    "graph": (GraphSlots, "One number drawn as a graph over its history."),
    "dog_counts": (DogCountsSlots, "Counts for the dogs, as label and number rows."),
    "list": (ListSlots, "A shopping or other list."),
    "todo": (TodoSlots, "A to-do list with done marks."),
    "alert": (AlertSlots, "A heads-up, at info, warning or urgent level."),
    "fun_fact": (FunFactSlots, "A short fact."),
}


class BlockProblem(ValueError):
    def __init__(self, problems: list[dict[str, str]]) -> None:
        super().__init__("; ".join(f"{p['slot']}: {p['problem']}" for p in problems))
        self.problems = problems


def catalogue() -> list[dict[str, Any]]:
    return [
        {"type": name, "description": text, "moods": list(MOODS) + [AUTO], "schema": f"/api/v1/blocks/{name}/schema"}
        for name, (_, text) in BLOCKS.items()
    ]


def block_schema(name: str) -> dict[str, Any]:
    model, text = BLOCKS[name]
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "title": name, "description": text,
            **model.model_json_schema()}


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
        try:
            slots = BLOCKS[name][0].model_validate(dict(raw.get("slots") or {}))
        except ValidationError as exc:
            for error in exc.errors():
                location = ".".join(str(part) for part in error["loc"]) or "slots"
                problems.append({"slot": f"{where}.slots.{location}", "problem": error["msg"]})
            continue
        checked.append({
            "type": name,
            "mood": "neutral" if mood == AUTO else mood,  # the decision model replaces this later
            "slots": slots.model_dump(exclude_none=True),
        })
    if problems:
        raise BlockProblem(problems)
    return checked


def entity_ids(blocks: Sequence[Mapping[str, Any]]) -> list[str]:
    found: list[str] = []
    for block in blocks:
        slots = block.get("slots", {})
        metrics = list(slots.get("metrics", []))
        if slots.get("metric"):
            metrics.append(slots["metric"])
        for metric in metrics:
            if metric.get("entity_id") and metric["entity_id"] not in found:
                found.append(metric["entity_id"])
    return found


def fetch_entities(blocks: Sequence[Mapping[str, Any]], client: HAClient | None) -> dict[str, str | None]:
    values: dict[str, str | None] = {}
    for entity in entity_ids(blocks):
        if client is None:
            values[entity] = None
            continue
        try:
            number = float(client.state(entity))
            values[entity] = str(int(number)) if number.is_integer() else f"{number:.1f}"
        except (HAError, ValueError, TypeError) as exc:
            logger.warning("entity %s unavailable: %s", entity, exc)
            values[entity] = None
    return values


def _metric_row(metric: Mapping[str, Any], values: Mapping[str, str | None]) -> Line:
    if metric.get("value") is not None:
        value = str(metric["value"])
    elif metric.get("series"):
        value = str(metric["series"][-1])
    else:
        value = values.get(metric.get("entity_id", ""), None) or "--"
    label = str(metric["label"]).upper()
    dots = max(2, PAPER_WIDTH - len(label) - len(value) - len(str(metric.get("unit") or "")) - 2)
    return Line(f"{label} {'.' * dots} {value}{metric.get('unit') or ''}")


def compose_lines(blocks: Sequence[Mapping[str, Any]], values: Mapping[str, str | None] | None = None) -> list[Line]:
    """Text layout of a composed ticket, block after block. Mood is not shown until the renderer lands."""
    values = values or {}
    lines: list[Line] = []
    for block in blocks:
        name = block["type"]
        slots = block.get("slots", {})
        if name == "greeting":
            lines.append(Line(str(slots["text"])))
        elif name == "title":
            lines.append(Line(str(slots["text"]).upper(), align="center", bold=True, tall=True))
        elif name in ("paragraph", "fun_fact", "alert"):
            lines.extend(Line(row) for row in wrap(str(slots["text"]), PAPER_WIDTH))
        elif name == "tip":
            lines.append(Line("-" * PAPER_WIDTH))
            lines.extend(Line(row) for row in wrap(f"Tip: {slots['text']}", PAPER_WIDTH))
        elif name == "message":
            lines.extend(Line(row) for row in wrap(str(slots["text"]), PAPER_WIDTH))
            lines.append(Line(f"- {slots['from_name']}", align="left"))
        elif name in ("metric_tiles", "metric_rows"):
            lines.extend(_metric_row(m, values) for m in slots["metrics"])
        elif name == "graph":
            lines.append(_metric_row(slots["metric"], values))
        elif name == "dog_counts":
            lines.append(Line(str(slots["label"]).upper()))
            lines.extend(_metric_row({"label": i["label"], "value": i["count"]}, values) for i in slots["items"])
        elif name == "list":
            if slots.get("title"):
                lines.append(Line(str(slots["title"]).upper(), bold=True))
            lines.extend(Line(f"- {item}") for item in slots["items"])
        elif name == "todo":
            if slots.get("title"):
                lines.append(Line(str(slots["title"]).upper(), bold=True))
            lines.extend(Line(f"[{'x' if i.get('done') else ' '}] {i['text']}") for i in slots["items"])
    return lines


def ticket_lines(slots: Mapping[str, Any], client: HAClient | None) -> list[Line]:
    """Lay out any stored slot ticket: a composed one, or a slot template (briefing and note)."""
    if "blocks" in slots:
        blocks = slots["blocks"]
        return compose_lines(blocks, fetch_entities(blocks, client))
    return slot_lines(slots, fetch_values(slots, client))
