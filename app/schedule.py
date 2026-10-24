"""Pure time rules for scheduled tickets. No I/O, so every rule is tested with a fake clock.

All instants are UTC epoch milliseconds, as in the store. Wall-clock times are interpreted in
the configured timezone (Europe/London by default).

DST rules:
- A local time that does not exist (spring forward, 01:00 to 02:00) runs at the first real
  instant after the gap. A 01:30 daily ticket therefore prints at 02:30 BST that morning.
- A local time that happens twice (autumn fall-back) runs once, at the first occurrence.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
DEFAULT_GRACE_MS = 15 * 60 * 1000  # a run up to 15 minutes late still prints


def parse_hhmm(value: str) -> time:
    """Parse 'HH:MM' (24 hour). Raises ValueError for anything else."""
    match = _HHMM.match(value.strip())
    if not match:
        raise ValueError(f"expected HH:MM, got {value!r}")
    return time(int(match.group(1)), int(match.group(2)))


def local_to_utc_ms(day: date, at: time, tz: ZoneInfo) -> int:
    """UTC ms for a wall-clock time on a day, using the rules in the module docstring."""
    naive = datetime.combine(day, at)
    # fold=0 picks the first occurrence of an ambiguous time.
    # zoneinfo maps a gap time with the offset from before the change, so 01:30 on spring
    # forward day lands on 02:30 BST, as the module docstring says.
    utc = naive.replace(tzinfo=tz).astimezone(UTC)
    return int(utc.timestamp() * 1000)


def next_daily_run_ms(at: time, tz: ZoneInfo, after_ms: int) -> int:
    """The next UTC ms strictly after after_ms when the local clock reads `at`."""
    after_local = datetime.fromtimestamp(after_ms / 1000, tz)
    day = after_local.date()
    for offset in range(3):  # today, tomorrow, the day after (covers any gap)
        candidate = local_to_utc_ms(day + timedelta(days=offset), at, tz)
        if candidate > after_ms:
            return candidate
    raise RuntimeError("no daily run found")  # unreachable: three days always cover it


def in_quiet_hours(now_ms: int, start: time, end: time, tz: ZoneInfo) -> bool:
    """True when the local clock is inside [start, end). Windows may cross midnight.

    A window with start == end is empty and never matches.
    """
    now_local = datetime.fromtimestamp(now_ms / 1000, tz).time()
    if start == end:
        return False
    if start < end:
        return start <= now_local < end
    return now_local >= start or now_local < end


def next_after_quiet(now_ms: int, start: time, end: time, tz: ZoneInfo) -> int:
    """If now is quiet, the first instant the quiet window ends. Otherwise now."""
    if not in_quiet_hours(now_ms, start, end, tz):
        return now_ms
    now_local = datetime.fromtimestamp(now_ms / 1000, tz)
    end_day = now_local.date()
    if start > end and now_local.time() >= start:
        end_day = end_day + timedelta(days=1)  # the window ends tomorrow morning
    return local_to_utc_ms(end_day, end, tz)


def catch_up(scheduled_ms: int, now_ms: int, grace_ms: int = DEFAULT_GRACE_MS) -> str:
    """What to do with a run whose time has passed, for example after a restart.

    'print'  the run is within the grace window, print it now;
    'skip'   it is too old to be useful (a morning briefing at 16:00 is wrong), mark it missed.
    """
    return "print" if now_ms - scheduled_ms <= grace_ms else "skip"


def latest_missed_run(
    at: time, tz: ZoneInfo, last_run_ms: int, now_ms: int
) -> int | None:
    """After downtime, a daily schedule has several missed runs. Only the newest one matters.

    Returns the newest occurrence in (last_run_ms, now_ms], or None when nothing was missed.
    Older misses are dropped, so a long outage prints one briefing, not one per day.
    """
    newest: int | None = None
    # Daily runs are at most a day apart, so a two day lookback still finds the newest one.
    cursor = max(last_run_ms, now_ms - 2 * 24 * 3600 * 1000)
    while True:
        nxt = next_daily_run_ms(at, tz, cursor)
        if nxt > now_ms:
            return newest
        newest = nxt
        cursor = nxt


def idempotency_key(*parts: str) -> str:
    """A stable key for one logical ticket, e.g. idempotency_key('morning', 'yannic', '2026-10-24')."""
    cleaned = [part.strip().lower().replace(" ", "-") for part in parts if part.strip()]
    if not cleaned:
        raise ValueError("an idempotency key needs at least one part")
    return ":".join(cleaned)[:120]
