"""Rate limit for the Telegram ping that threads send (POST /api/v1/notify).

One message per source every `interval` seconds. A source is the caller's address: a thread on
the same machine shares a limit, which is what keeps a runaway loop from flooding the chat.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

MAX_TEXT = 1000  # characters; Telegram allows 4096, a restart note needs far less


class NotifyLimiter:
    def __init__(self, interval: float = 60.0, clock: Callable[[], float] = time.monotonic) -> None:
        self.interval = interval
        self.clock = clock
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def check(self, source: str) -> float:
        """Take a turn for this source. Returns 0 when the message may go now, else the seconds to wait."""
        with self._lock:
            now = self.clock()
            last = self._last.get(source)
            if last is not None and now - last < self.interval:
                return self.interval - (now - last)
            self._last[source] = now
            return 0.0


def clean_text(text: str) -> str:
    """Printable text only: control characters other than newline are dropped."""
    return "".join(ch for ch in text if ch == "\n" or ch.isprintable())
