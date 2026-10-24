"""Process-local counters for /api/v1/metrics. They reset on restart; the database keeps the tickets."""

from __future__ import annotations

import threading
import time


class Metrics:
    def __init__(self, clock=time.time) -> None:
        self._lock = threading.Lock()
        self._counts: dict[str, int] = {}
        self._started = clock()
        self._clock = clock

    def incr(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self._counts[name] = self._counts.get(name, 0) + amount

    def snapshot(self) -> dict[str, float | dict[str, int]]:
        with self._lock:
            counts = dict(sorted(self._counts.items()))
        return {"uptime_seconds": round(self._clock() - self._started, 1), "counters": counts}
