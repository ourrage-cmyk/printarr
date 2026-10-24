"""Composed tickets: an ordered list of typed blocks, drawn as receipt strips.

A block is {type, mood, span, slots}. The types, moods, spans and sizes come from the renderer
(app/render/strips.py and app/render/system/blocks.json), so what is checked here is what gets drawn.
The renderer is pure, so Home Assistant values are read first and filled into the slots. Text that
runs past its card's height is shortened with "..." and reported as a note.
"""

from __future__ import annotations

import logging
from datetime import datetime, tzinfo
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.ha import HAClient, HAError
from app.receipt import Line as ReceiptLine
from app.receipt import format_number
from app.render import strips as R
from app.slots import BRIEFING, NOTE, fetch_values

logger = logging.getLogger("printarr.compose")

MOODS: tuple[str, ...] = tuple(R.MOODS)
AUTO = "auto"  # the decision model picks the mood; the rules pick neutral until it does
MAX_BLOCKS = 16
PLACEHOLDER = "--"  # printed for a value Home Assistant did not give
DISPLAY_TZ: tzinfo | None = None  # the household's time zone, set at start-up from the settings
TICKET_MARGIN = 0  # a composed ticket carries no blank: the space before the cut is fed with the cut command
TICKET_MARGIN_BOTTOM = 0
CARD_CAPTION = "[card]"  # what a text preview shows in place of a drawn card
HISTORY_POINTS = 48  # sparkline points: the renderer draws at most this many


class BlockProblem(ValueError):
    def __init__(self, problems: list[dict[str, str]]) -> None:
        super().__init__("; ".join(f"{p['slot']}: {p['problem']}" for p in problems))
        self.problems = problems


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class MetricRow(_Strict):
    label: str = Field(min_length=1, max_length=20, description="Short name, printed in capitals. A tile is a third of the paper wide.")
    value: int | float | str | None = Field(default=None, description="The number or text to print.")
    unit: str | None = Field(default=None, max_length=12)
    entity_id: str | None = Field(default=None, max_length=120, description="Home Assistant entity, read at print time.")
    scope: str | None = Field(default=None, pattern="^(inside|outside)$", description="Where the reading is taken: inside or outside. Printed as IN or OUT after the label.")

    @model_validator(mode="after")
    def _has_value(self) -> MetricRow:
        if self.value is None and self.entity_id is None:
            raise ValueError("send a value (a number or text) or an entity_id (a Home Assistant entity, such as sensor.steps)")
        return self


class MetricSlots(MetricRow):
    series: list[float] | None = Field(default=None, min_length=2, max_length=48, description="Sparkline, oldest first.")
    range: str | None = Field(default=None, max_length=8, description="The time the sparkline covers, such as 24H. Default 24H.")
    as_of: str | None = Field(default=None, max_length=16, description="When the reading was taken, for example 08:15. Printed as AS OF 08:15.")


class MetricRowsSlots(_Strict):
    title: str | None = Field(default=None, min_length=1, max_length=40)
    as_of: str | None = Field(default=None, max_length=16, description="When the readings were taken, for example 08:15. Printed once under the rows as AS OF 08:15.")
    rows: list[MetricRow] = Field(min_length=1, max_length=6)


class GreetingSlots(_Strict):
    greeting: str = Field(min_length=1, max_length=40, description="For example HELLO YANNIC.")
    summary: str | None = Field(default=None, min_length=1, max_length=200)
    sign_off: str | None = Field(default=None, alias="from", min_length=1, max_length=20, description="Who the greeting is from. Printed at the bottom; a lone greeting takes the ticket's sender when this is omitted.")


class GraphSlots(_Strict):
    title: str = Field(min_length=1, max_length=40)
    series: list[float] = Field(min_length=2, max_length=48, description="Values, oldest first.")
    unit: str | None = Field(default=None, max_length=12)
    range: str | None = Field(default=None, max_length=8, description="The time the series covers, such as 24H or 12H. Default 24H.")


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
    sign_off: str | None = Field(default=None, alias="from", min_length=1, max_length=20, description="Who the alert is from, for example Allyson. Printed at the bottom; the ticket's sender is used when omitted.")


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
            live = slots.get("value") is None and bool(slots.get("entity_id"))
            slots = _filled_row(slots, values)
            if live and not slots.get("as_of"):
                slots["as_of"] = datetime.now(DISPLAY_TZ).strftime("%H:%M")  # a live reading says when it was read
        if block["type"] == "metric_rows":
            live = any(row.get("value") is None and row.get("entity_id") for row in slots.get("rows", []))
            slots["rows"] = [_filled_row(row, values) for row in slots.get("rows", [])]
            if live and not slots.get("as_of"):
                slots["as_of"] = datetime.now(DISPLAY_TZ).strftime("%H:%M")
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
    strips = R.split_strips(_render_blocks(filled))
    for i, strip in enumerate(strips):
        # One piece of paper: the cut margins belong to the ends of the ticket, strips inside it are one tile gap apart.
        top = TICKET_MARGIN if i == 0 else R.GAP_V
        bottom = TICKET_MARGIN_BOTTOM if i == len(strips) - 1 else 0
        bitmap, strip_notes = R.render_strip_with_notes(strip, margin_top=top, margin_bottom=bottom)
        lines.append(ReceiptLine(CARD_CAPTION, raster=(bitmap.width // 8, bitmap.height, bitmap.bits)))
        notes.extend(strip_notes)
    return lines, notes


def summary(blocks: Sequence[Mapping[str, Any]]) -> str:
    """A short label for the ticket's log row, taken from its first block."""
    first = blocks[0]["slots"]
    for key in ("greeting", "label", "paragraph", "title", "tip"):
        if first.get(key):
            return str(first[key])
    return "(composed)"


def _plain(value: Any) -> Any:
    """A whole number prints without its .0."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _history(entity_id: str, hours: int, client: HAClient | None) -> list[float] | None:
    """Up to HISTORY_POINTS numeric states, oldest first. None when Home Assistant gives no history."""
    if client is None:
        return None
    try:
        values = client.numeric_history(entity_id, hours)
    except (HAError, ValueError, TypeError) as exc:
        logger.warning("history for %s unavailable: %s", entity_id, exc)
        return None
    if len(values) < 2:
        return None
    step = -(-len(values) // HISTORY_POINTS)  # ceiling division: spread the points across the window
    return values[::step][-HISTORY_POINTS:]


def _metric_block(metric: Mapping[str, Any], client: HAClient | None) -> dict[str, Any]:
    """One briefing metric as a metric card. Entity metrics get a sparkline of their history."""
    slots: dict[str, Any] = {"label": metric["label"]}
    if metric.get("unit"):
        slots["unit"] = metric["unit"]
    if metric.get("series"):
        slots["series"] = list(metric["series"])
        slots["value"] = _plain(metric["series"][-1])
    elif metric.get("value") is not None:
        slots["value"] = _plain(metric["value"])
    else:
        slots["entity_id"] = metric["entity_id"]  # the value is read at print time
        history = _history(metric["entity_id"], metric.get("hours") or 24, client)
        if history:
            slots["series"] = history
    for key in ("scope", "as_of"):
        if metric.get(key):
            slots[key] = metric[key]
    if "entity_id" in slots and "as_of" not in slots:
        slots["as_of"] = datetime.now(DISPLAY_TZ).strftime("%H:%M")  # a live reading says when it was read
    return {"type": "metric", "mood": "factual", "span": 1, "slots": slots}


ADDRESSEES = {"yannic": "YANNIC", "wife": "ALLYSON"}  # the name printed on a briefing that sends no greeting


def time_of_day(hour: int) -> str:
    return "MORNING" if hour < 12 else "AFTERNOON" if hour < 18 else "EVENING"


def addressee_greeting(recipient: str | None) -> str | None:
    """The name and time of day that head a briefing sent without a greeting, so the paper shows who it is for."""
    name = ADDRESSEES.get(str(recipient or "").lower())
    if name is None:
        return None
    return f"{name} {time_of_day(datetime.now(DISPLAY_TZ).hour)}"


def briefing_blocks(
    slots: Mapping[str, Any], client: HAClient | None, sender: str | None = None, recipient: str | None = None
) -> list[dict[str, Any]]:
    """A briefing (template 101) as blocks: a greeting, one metric card per number, and a tip."""
    blocks: list[dict[str, Any]] = []
    head = slots.get("title") or slots.get("greeting")  # a title, when sent, is the headline; the greeting leads the text
    text = slots.get("paragraph")
    if slots.get("title") and slots.get("greeting") and not text:
        text = slots["greeting"]  # a title and a greeting with no text: the greeting is the subtitle; with text it is dropped
    head = head or (addressee_greeting(recipient) if slots.get("metrics") or slots.get("tip") or text else None)
    if head or text:
        greeting: dict[str, Any] = {"greeting": head or "TODAY", "_group": True}  # a briefing is one nested card
        if text:
            greeting["summary"] = text  # the renderer shortens it if it runs long
        signer = slots.get("from") or slots.get("sign_off") or sender
        if signer and not slots.get("tip") and not slots.get("metrics"):
            greeting["from"] = signer  # nothing below carries the signature, so the greeting does
        blocks.append({"type": "greeting", "mood": "neutral", "span": 3, "slots": greeting})
    blocks.extend(_metric_block(metric, client) for metric in slots.get("metrics", []))
    if slots.get("tip"):
        tip_slots = {"tip": slots["tip"]}
        signer = slots.get("from") or slots.get("sign_off") or sender
        if signer:
            tip_slots["from"] = signer
        blocks.append({"type": "tip", "mood": "reminder", "span": 3, "slots": tip_slots})
    return blocks


def message_blocks(paragraph: str, sender: str | None, title: str | None = None, tip: str | None = None) -> list[dict[str, Any]]:
    """A note as one message card, signed off by the sender."""
    slots: dict[str, Any] = {"paragraph": paragraph, "from": sender or "Printarr"}
    if title:
        slots["title"] = title
    if tip:
        slots["tip"] = tip
    return [{"type": "message", "mood": "neutral", "span": 3, "slots": slots}]


def note_card_render(message: str, sender: str | None, title: str | None = None) -> tuple[list[ReceiptLine], list[str]]:
    """A plain note drawn as a message card, with the notes for any text that was shortened to fit."""
    lines, notes = compose_render(message_blocks(message, sender, title=title), None)
    return [ReceiptLine(message, raster=line.raster) for line in lines], notes  # the caption keeps the text for the log


def note_card_lines(message: str, sender: str | None, title: str | None = None) -> list[ReceiptLine]:
    """A plain note (from the /tickets API) drawn as a message card, in the shared shell."""
    return note_card_render(message, sender, title)[0]


def sign_blocks(blocks: Sequence[Mapping[str, Any]], sender: str | None) -> list[Mapping[str, Any]]:
    """Signs the blocks that carry someone's words. A lone greeting is signed too: nothing else on the strip would."""
    signed = [_signed(block, sender) for block in blocks]
    if len(signed) == 1 and signed[0].get("type") == "greeting" and sender and not signed[0].get("slots", {}).get("from"):
        signed[0] = {**signed[0], "slots": {**signed[0]["slots"], "from": sender}}
    return signed


def _signed(block: Mapping[str, Any], sender: str | None) -> Mapping[str, Any]:
    """A card that carries someone's words is never anonymous: an alert without a sign-off takes the ticket's sender."""
    if block.get("type") == "alert" and sender and not block.get("slots", {}).get("from"):
        return {**block, "slots": {**block["slots"], "from": sender}}
    return block


def ticket_lines(
    slots: Mapping[str, Any],
    client: HAClient | None,
    template_id: int | None = None,
    sender: str | None = None,
    recipient: str | None = None,
) -> list[ReceiptLine]:
    """Lay out a stored slot ticket. Composed tickets, briefings and notes all draw as cards."""
    if "blocks" in slots:
        blocks = sign_blocks(slots["blocks"], sender)
    elif template_id == NOTE or ("paragraph" in slots and "metrics" not in slots):
        blocks = message_blocks(str(slots["paragraph"]), sender, title=slots.get("title"), tip=slots.get("tip"))
    elif template_id == BRIEFING or "metrics" in slots:
        blocks = briefing_blocks(slots, client, sender, recipient)
    elif "greeting" in slots:
        blocks = [{"type": "greeting", "mood": "neutral", "span": 3, "slots": {k: slots[k] for k in ("greeting", "summary") if slots.get(k)}}]
        if sender and not slots.get("tip"):
            blocks[0]["slots"]["from"] = sender
        if slots.get("tip"):
            blocks.append({"type": "tip", "mood": "neutral", "span": 3, "slots": {"tip": str(slots["tip"])}})
    else:
        blocks = message_blocks(str(slots.get("title") or "Printarr"), sender)
    lines, _ = compose_render(blocks, client)
    return lines


# The briefing preset: one fixed layout for Hermes' morning (or evening) briefing, so every briefing
# looks like the same ticket. Greeting with the time of day, three metrics with sparklines, one larger
# graph, a body and a fun fact. Each part is a block, so each prints as its own tile.
PRESET_BRIEFING = "briefing"
PRESET_METRICS = 3


class PresetMetric(_Strict):
    label: str = Field(min_length=1, max_length=40)
    entity_id: str | None = Field(default=None, max_length=120, description="Home Assistant entity: its value is read at print time and its history draws the sparkline.")
    value: int | float | str | None = Field(default=None, description="A fixed value, when there is no entity.")
    unit: str | None = Field(default=None, max_length=12)
    hours: int = Field(default=24, ge=1, le=168, description="How far back the sparkline reaches.")

    @model_validator(mode="after")
    def _has_value(self) -> PresetMetric:
        if self.value is None and self.entity_id is None:
            raise ValueError("send a value or an entity_id (a Home Assistant entity, such as sensor.steps)")
        return self


class PresetGraph(_Strict):
    title: str = Field(min_length=1, max_length=40)
    entity_id: str | None = Field(default=None, max_length=120, description="Home Assistant entity whose history draws the graph. Left out when there is no history.")
    series: list[float] | None = Field(default=None, min_length=2, max_length=48, description="Fixed values, oldest first, when there is no entity.")
    hours: int = Field(default=24, ge=1, le=168)
    unit: str | None = Field(default=None, max_length=12)

    @model_validator(mode="after")
    def _has_data(self) -> PresetGraph:
        if self.series is None and self.entity_id is None:
            raise ValueError("send series (values, oldest first) or an entity_id")
        return self


class BriefingPresetSlots(_Strict):
    time_of_day: Literal["morning", "afternoon", "evening"] = Field(description="The headline reads GOOD MORNING, GOOD AFTERNOON or GOOD EVENING.")
    metrics: list[PresetMetric] = Field(min_length=PRESET_METRICS, max_length=PRESET_METRICS, description="Exactly three entities, each with a sparkline.")
    graph: PresetGraph = Field(description="The one larger graph under the metrics.")
    body: str = Field(min_length=1, max_length=800, description="The briefing text, in a message card.")
    fun_fact: str = Field(min_length=1, max_length=200, description="A short fun fact, printed as a fact card.")
    sign_off: str | None = Field(default=None, alias="from", min_length=1, max_length=20, description="Who the briefing is from. The ticket's sender is used when omitted.")



def _preset_greeting(time_of_day: str, recipient: str | None) -> str:
    """GOOD MORNING, with the addressee's name after it when the recipient is known."""
    greeting = f"GOOD {time_of_day.upper()}"
    name = ADDRESSEES.get(str(recipient or "").lower())
    return f"{greeting} {name}" if name else greeting


def briefing_preset_blocks(
    slots: Mapping[str, Any], client: HAClient | None, sender: str | None = None, recipient: str | None = None
) -> list[dict[str, Any]]:
    """The briefing preset as blocks, in print order. Raises BlockProblem naming each wrong slot."""
    try:
        parsed = BriefingPresetSlots.model_validate(dict(slots))
    except ValidationError as exc:
        raise BlockProblem(_slot_problems("preset", exc)) from None
    blocks: list[dict[str, Any]] = [{
        "type": "greeting", "mood": "neutral", "span": 3,
        "slots": {"greeting": _preset_greeting(parsed.time_of_day, recipient)},
    }]
    blocks.extend(_metric_block(metric.model_dump(exclude_none=True), client) for metric in parsed.metrics)
    graph = parsed.graph
    series = list(graph.series) if graph.series is not None else _history(graph.entity_id, graph.hours, client)
    if series:  # no history from Home Assistant: the graph is left out and the rest still prints
        graph_slots: dict[str, Any] = {"title": graph.title, "series": series, "range": f"{graph.hours}H"}
        if graph.unit:
            graph_slots["unit"] = graph.unit
        blocks.append({"type": "graph", "mood": "factual", "span": 3, "slots": graph_slots})
    blocks.extend(message_blocks(parsed.body, parsed.sign_off or sender))
    blocks.append({"type": "fact", "mood": "playful", "span": 3, "slots": {"paragraph": parsed.fun_fact}})
    return blocks
