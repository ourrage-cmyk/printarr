"""Image designs the printer can print, and the Home Assistant entities each one reads.

Adding a design means one entry in DESIGNS: which entities it reads, and how to draw it.
Every value is a number or None. None prints "NO DATA", and the layout does not move.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from app.ha import HAClient, HAError
from app.receipt import Line
from app.render.canvas import Bitmap
from app.render.designs import Morning, morning_yannic

logger = logging.getLogger("printarr.render")

Values = Mapping[str, float | None]


@dataclass(frozen=True)
class Design:
    entities: Mapping[str, str]  # value name -> Home Assistant entity id
    build: Callable[[Values, str], Bitmap]  # (values, summary sentence) -> bitmap


def _whole(value: float | None) -> int | None:
    return None if value is None else round(value)


def _build_morning(values: Values, summary: str) -> Bitmap:
    return morning_yannic(
        Morning(
            summary=summary,
            body_battery=_whole(values.get("body_battery")),
            stress=_whole(values.get("stress")),
            steps=_whole(values.get("steps")),
            cpu=_whole(values.get("cpu")),
            ram=_whole(values.get("ram")),
        )
    )


DESIGNS: dict[str, Design] = {
    "morning": Design(
        entities={
            "body_battery": "sensor.body_battery_most_recent",
            "stress": "sensor.avg_stress_level",
            "steps": "sensor.total_steps",
            "cpu": "sensor.truenas_cpu_usage",
            "ram": "sensor.system_monitor_memory_usage",
        },
        build=_build_morning,
    ),
}


def _number(state: str) -> float | None:
    """A Home Assistant state as a number. Unavailable, unknown or non-numeric is None."""
    try:
        return float(state)
    except ValueError:
        return None


def fetch_values(design: Design, client: HAClient | None) -> dict[str, float | None]:
    """Read every entity of a design at once. A failed or missing entity is None."""
    if client is None:
        return {name: None for name in design.entities}

    def read(entity_id: str) -> float | None:
        try:
            return _number(client.state(entity_id))
        except HAError as exc:
            logger.warning("entity %s unavailable: %s", entity_id, exc)
            return None

    with ThreadPoolExecutor(max_workers=len(design.entities)) as pool:
        futures = {name: pool.submit(read, entity) for name, entity in design.entities.items()}
        return {name: future.result() for name, future in futures.items()}


def design_line(name: str, summary: str, client: HAClient | None) -> tuple[Line, bool]:
    """The ticket's image line, and whether every value was missing (Home Assistant is down)."""
    design = DESIGNS[name]
    values = fetch_values(design, client)
    bitmap = design.build(values, summary)
    line = Line("", raster=(bitmap.width // 8, bitmap.height, bitmap.bits))
    return line, all(value is None for value in values.values())


def placeholder_line(name: str, summary: str) -> Line:
    """The same layout with every value missing. Used to check a ticket and to preview it."""
    return design_line(name, summary, None)[0]
