"""Slot-based templates. A template declares typed slots; the caller fills them.

Hermes, Home Assistant or the web page fills the slots and chooses the data. printarr checks
the slots, fills in any that were left out, reads live Home Assistant values at print time and
lays out the ticket. A slot template's ticket stores its filled slots with it, for the log.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.ha import HAClient, HAError
from app.receipt import Line, format_number, wrap

logger = logging.getLogger("printarr.slots")

PAPER_WIDTH = 42
SLOT_GROUP = "slots"
BRIEFING = 101
NOTE = 102
NO_VALUE = "--"

Recipient = Literal["yannic", "wife"]
RECIPIENTS = {"yannic": "Yannic", "wife": "Allyson"}

# Entities a briefing shows when the caller gives none. Yannic's come from the morning design.
DEFAULT_METRICS: dict[str, list[dict[str, Any]]] = {
    "yannic": [
        {"label": "BODY BATTERY", "entity_id": "sensor.body_battery_most_recent", "unit": "%"},
        {"label": "STRESS AVG", "entity_id": "sensor.avg_stress_level"},
        {"label": "STEPS", "entity_id": "sensor.total_steps"},
        {"label": "CPU", "entity_id": "sensor.truenas_cpu_usage", "unit": "%"},
    ],
    "wife": [],
}

TIPS = (
    "Drink a glass of water before the first coffee.",
    "Check the bins before you leave.",
    "Leave five minutes early today.",
    "Put tomorrow's keys by the door tonight.",
    "A short walk after lunch helps the afternoon.",
)


class Metric(BaseModel):
    """One number to draw as a value and a graph. Give an entity to read Home Assistant, or literal data."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=20, description="Short name, printed in capitals.")
    entity_id: str | None = Field(
        default=None,
        max_length=120,
        pattern=r"^[a-z_]+\.[a-z0-9_]+$",
        description="A Home Assistant entity, read at print time. For example sensor.total_steps.",
    )
    value: float | None = Field(default=None, description="A literal value, for data that is not in Home Assistant.")
    series: list[float] | None = Field(
        default=None, max_length=48, description="Literal history, oldest first. Its last value is shown."
    )
    unit: str | None = Field(default=None, max_length=8, examples=["%"])
    hours: int | None = Field(default=None, ge=1, le=168, description="Hours of history to graph, for entities.")
    scope: Literal["inside", "outside"] | None = Field(default=None, description="Where the reading is taken. Printed as IN or OUT after the label.")
    as_of: str | None = Field(default=None, max_length=16, description="When the reading was taken, for example 08:15. Printed as AS OF 08:15.")

    @model_validator(mode="after")
    def one_source(self) -> Metric:
        sources = sum(x is not None for x in (self.entity_id, self.value, self.series))
        if sources != 1:
            raise ValueError("give exactly one of entity_id, value or series")
        if self.series is not None and not self.series:
            raise ValueError("series must not be empty")
        return self


class BriefingSlots(BaseModel):
    model_config = ConfigDict(extra="forbid")

    greeting: str | None = Field(default=None, max_length=40, examples=["Good morning, Yannic"])
    title: str | None = Field(default=None, max_length=60, examples=["Today"])
    metrics: list[Metric] = Field(default_factory=list, max_length=4, description="Up to four graphed numbers.")
    paragraph: str | None = Field(default=None, max_length=400, description="The briefing text.")
    formatted: bool = Field(default=True, description="False when the text is raw speech to clean up.")
    tip: str | None = Field(default=None, max_length=120, examples=["Leave five minutes early."])
    sign_off: str | None = Field(default=None, alias="from", max_length=20, description="Who the briefing is from. Printed under the tip; the ticket's sender is used when omitted.")


class NoteSlots(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=60)
    paragraph: str = Field(min_length=1, max_length=800, description="The message.")
    tip: str | None = Field(default=None, max_length=120, description="A closing line, such as a reminder.")


SLOT_MODELS: dict[int, type[BaseModel]] = {BRIEFING: BriefingSlots, NOTE: NoteSlots}
SLOT_NAMES: dict[int, str] = {BRIEFING: "Briefing", NOTE: "Note"}


class SlotProblems(ValueError):
    """The slots do not match the template. problems lists each one as {slot, problem}."""

    def __init__(self, problems: list[dict[str, str]]) -> None:
        super().__init__("; ".join(f"{p['slot']}: {p['problem']}" for p in problems))
        self.problems = problems


def is_slot_template(template_id: int) -> bool:
    return template_id in SLOT_MODELS


def schema(template_id: int) -> dict[str, Any]:
    model = SLOT_MODELS[template_id]
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": SLOT_NAMES[template_id],
        **model.model_json_schema(),
    }


def validate(template_id: int, raw: Mapping[str, Any]) -> BaseModel:
    """Check the slots. Raises SlotProblems that name each slot which is wrong."""
    try:
        return SLOT_MODELS[template_id].model_validate(dict(raw))
    except ValidationError as exc:
        problems = []
        for error in exc.errors():
            location = ".".join(str(part) for part in error["loc"]) or "slots"
            problems.append({"slot": location, "problem": error["msg"]})
        raise SlotProblems(problems) from None


def greeting_for(when: datetime, recipient: str) -> str:
    hour = when.hour
    part = "morning" if hour < 12 else "afternoon" if hour < 18 else "evening"
    return f"Good {part}, {RECIPIENTS.get(recipient, recipient)}"


def autofill(template_id: int, slots: Mapping[str, Any], recipient: str, when: datetime) -> dict[str, Any]:
    """Fill the slots the caller left out, so a bare request still prints something good."""
    filled = {key: value for key, value in slots.items() if value not in (None, "", [])}
    if template_id == BRIEFING:
        filled.setdefault("greeting", greeting_for(when, recipient))
        if not filled.get("metrics"):
            filled["metrics"] = [dict(m) for m in DEFAULT_METRICS.get(recipient, [])]
    filled.setdefault("tip", TIPS[when.timetuple().tm_yday % len(TIPS)])
    return filled


def _number(value: float) -> str:
    return format_number(value)


def literal_text(metric: Mapping[str, Any]) -> str | None:
    if metric.get("value") is not None:
        return _number(metric["value"])
    if metric.get("series"):
        return _number(metric["series"][-1])
    return None


def fetch_values(slots: Mapping[str, Any], client: HAClient | None) -> list[str | None]:
    """Read each entity metric now. One per metric, aligned by position. Missing values are None."""
    results: list[str | None] = []
    for metric in slots.get("metrics", []):
        if not metric.get("entity_id"):
            results.append(None)
            continue
        if client is None:
            results.append(None)
            continue
        try:
            results.append(_number(float(client.state(metric["entity_id"]))))
        except (HAError, ValueError, TypeError) as exc:
            logger.warning("metric %s unavailable: %s", metric["entity_id"], exc)
            results.append(None)
    return results


def _row(label: str, value: str) -> Line:
    dots = max(2, PAPER_WIDTH - len(label) - len(value) - 2)
    return Line(f"{label} {'.' * dots} {value}")


def slot_lines(slots: Mapping[str, Any], fetched: Sequence[str | None] | None = None) -> list[Line]:
    """The ticket as text lines. Graphs are a later step; each metric prints its value now."""
    lines: list[Line] = []
    if slots.get("title"):
        lines.append(Line(str(slots["title"]).upper(), align="center", bold=True, tall=True))
    if slots.get("greeting"):
        lines.append(Line(str(slots["greeting"])))
    fetched = list(fetched) if fetched is not None else []
    for index, metric in enumerate(slots.get("metrics", [])):
        value = literal_text(metric)
        if value is None:
            value = fetched[index] if index < len(fetched) and fetched[index] else NO_VALUE
        unit = metric.get("unit") or ""
        spaced = f" {unit}" if unit[:1].isalpha() else unit
        lines.append(_row(str(metric["label"]).upper(), f"{value}{spaced}"))
    if slots.get("paragraph"):
        lines.extend(Line(row) for row in wrap(str(slots["paragraph"]), PAPER_WIDTH))
    if slots.get("tip"):
        lines.append(Line("-" * PAPER_WIDTH))
        lines.extend(Line(row) for row in wrap(f"Tip: {slots['tip']}", PAPER_WIDTH))
    return lines
