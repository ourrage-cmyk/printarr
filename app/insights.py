"""Pick the Home Assistant numbers that are worth a graph on a briefing.

Hermes gets a ranked list of candidate entities for one person. Each has its current value,
its 30-day mean and spread, a z-score (how unusual it is), a 7-day trend, and a relevance
weight for that person. Hermes picks the four slots from this list and writes the text.

Scoring is pure and takes history as plain lists, so tests run without Home Assistant.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass

HistoryFn = Callable[[str, int], list[float]]

CACHE_TTL_S = 300.0  # five minutes: a briefing does not need fresher numbers than this
WINDOW_HOURS = 30 * 24
TREND_MIN_CHANGE = 0.05  # 5% change between the two halves of the week counts as a trend


@dataclass(frozen=True)
class Candidate:
    entity_id: str
    label: str
    unit: str
    owner: str | None  # "yannic", "wife", or None for shared house data
    category: str  # body, sleep, activity, house, energy, pets, weather


# Numeric entities from docs/design/ha-entities.md. Keep this list to entities that have history.
CATALOG: tuple[Candidate, ...] = (
    Candidate("sensor.body_battery_most_recent", "Body battery", "%", "yannic", "body"),
    Candidate("sensor.sleep_score", "Sleep score", "", "yannic", "sleep"),
    Candidate("sensor.avg_stress_level", "Stress", "", "yannic", "body"),
    Candidate("sensor.total_steps", "Steps", "steps", "yannic", "activity"),
    Candidate("sensor.resting_heart_rate", "Resting heart rate", "bpm", "yannic", "body"),
    Candidate("sensor.yannic_pixel_battery_level", "Phone battery", "%", "yannic", "device"),
    Candidate("sensor.body_battery_most_recent_2", "Body battery", "%", "wife", "body"),
    Candidate("sensor.sleep_score_2", "Sleep score", "", "wife", "sleep"),
    Candidate("sensor.avg_stress_level_2", "Stress", "", "wife", "body"),
    Candidate("sensor.total_steps_2", "Steps", "steps", "wife", "activity"),
    Candidate("sensor.resting_heart_rate_2", "Resting heart rate", "bpm", "wife", "body"),
    Candidate("sensor.garmin_connect_hrv_last_night_average_2", "HRV last night", "ms", "wife", "body"),
    Candidate("sensor.allyson_pixel_battery_level", "Phone battery", "%", "wife", "device"),
    Candidate("sensor.home_temperature", "Home", "°C", None, "house"),
    Candidate("sensor.home_humidity", "Humidity", "%", None, "house"),
    Candidate("sensor.realtime_energy_cost", "Energy cost now", "£/h", None, "energy"),
    Candidate("sensor.money_saved_rate", "Saving rate", "£/h", None, "energy"),
    Candidate("sensor.truenas_pool_usage", "Storage used", "%", None, "house"),
    Candidate("sensor.truenas_cpu_usage", "NAS CPU", "%", None, "house"),
    Candidate("counter.bridget_poop", "Bridget poop", "", None, "pets"),
    Candidate("counter.kida_poop", "Kida poop", "", None, "pets"),
    Candidate("counter.bridget_runs", "Bridget runs", "", None, "pets"),
    Candidate("counter.kida_runs", "Kida runs", "", None, "pets"),
)


@dataclass(frozen=True)
class Insight:
    entity_id: str
    label: str
    unit: str
    category: str
    owner: str | None
    current: float
    mean_30d: float
    stdev_30d: float
    z_score: float
    trend: str  # "up", "down", "flat"
    trend_pct: float
    relevance: int
    score: float
    why: str


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _stdev(values: list[float], mean: float) -> float:
    if len(values) < 2:
        return 0.0
    return math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1))


def score_series(values: list[float]) -> dict[str, float | str] | None:
    """Stats for an oldest-first series. None when there is too little data to say anything."""
    if len(values) < 5:
        return None
    current = values[-1]
    mean = _mean(values)
    spread = _stdev(values, mean)
    z = 0.0 if spread == 0 else (current - mean) / spread
    # Trend: last 7 days against the 7 days before them, if the series covers 14 days.
    week = max(1, len(values) // 4)
    recent, earlier = _mean(values[-week:]), _mean(values[-2 * week:-week] or values[:week])
    change = 0.0 if earlier == 0 else (recent - earlier) / abs(earlier)
    trend = "flat"
    if change >= TREND_MIN_CHANGE:
        trend = "up"
    elif change <= -TREND_MIN_CHANGE:
        trend = "down"
    return {"current": current, "mean": mean, "stdev": spread, "z": z, "trend": trend, "change": change}


def relevance_for(candidate: Candidate, person: str) -> int:
    """Three points for the person's own data, one for shared house data, none for the other person."""
    if candidate.owner == person:
        return 3
    if candidate.owner is None:
        return 1
    return 0


def build_insight(candidate: Candidate, values: list[float], person: str) -> Insight | None:
    stats = score_series(values)
    if stats is None:
        return None
    relevance = relevance_for(candidate, person)
    if relevance == 0:
        return None
    z = float(stats["z"])
    # An unusual reading matters more than a typical one. Own data is weighted above shared data.
    score = abs(z) + 0.5 * abs(float(stats["change"])) * 10 + relevance * 0.5
    why = _why(z, str(stats["trend"]), float(stats["change"]))
    return Insight(
        entity_id=candidate.entity_id,
        label=candidate.label,
        unit=candidate.unit,
        category=candidate.category,
        owner=candidate.owner,
        current=round(float(stats["current"]), 2),
        mean_30d=round(float(stats["mean"]), 2),
        stdev_30d=round(float(stats["stdev"]), 2),
        z_score=round(z, 2),
        trend=str(stats["trend"]),
        trend_pct=round(float(stats["change"]) * 100, 1),
        relevance=relevance,
        score=round(score, 3),
        why=why,
    )


def _why(z: float, trend: str, change: float) -> str:
    if abs(z) >= 2:
        return "well outside the usual range"
    if abs(z) >= 1:
        return "above its usual level" if z > 0 else "below its usual level"
    if trend != "flat":
        return f"trending {trend} this week ({change * 100:+.0f}%)"
    return "steady"


def rank(insights: list[Insight], limit: int) -> list[Insight]:
    return sorted(insights, key=lambda i: (-i.score, i.entity_id))[:limit]


def candidates_for(person: str) -> tuple[Candidate, ...]:
    return tuple(c for c in CATALOG if c.owner in (person, None))


def collect(person: str, history: HistoryFn, limit: int) -> list[Insight]:
    """Score every candidate for this person with the given history reader."""
    results = []
    for candidate in candidates_for(person):
        try:
            values = history(candidate.entity_id, WINDOW_HOURS)
        except Exception:  # one missing entity must not hide the rest
            continue
        insight = build_insight(candidate, values, person)
        if insight is not None:
            results.append(insight)
    return rank(results, limit)


class InsightCache:
    """Keeps the last answer per (person, limit) for CACHE_TTL_S seconds."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._items: dict[tuple[str, int], tuple[float, list[Insight]]] = {}

    def get(self, person: str, limit: int, compute: Callable[[], list[Insight]]) -> list[Insight]:
        key = (person, limit)
        now = self._clock()
        cached = self._items.get(key)
        if cached and now - cached[0] < CACHE_TTL_S:
            return cached[1]
        fresh = compute()
        self._items[key] = (now, fresh)
        return fresh
