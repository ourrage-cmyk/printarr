"""Background worker that prints tickets once they are due, with retries."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from app.config import Settings
from app.escpos import encode
from app.printer import Transport
from app.receipt import receipt_for_ticket, render_lines
from app.store import TicketStore, now_ms

logger = logging.getLogger("printarr.scheduler")

BATCH_SIZE = 10


class Scheduler:
    def __init__(
        self,
        store: TicketStore,
        transport: Transport,
        settings: Settings,
        clock: Callable[[], int] = now_ms,
    ) -> None:
        self.store = store
        self.transport = transport
        self.settings = settings
        self.clock = clock

    def run_once(self) -> int:
        """Print every ticket that is due right now. Returns how many were attempted."""
        jobs = self.store.claim_due(self.clock(), BATCH_SIZE)
        for ticket in jobs:
            self._print(ticket)
        return len(jobs)

    def _print(self, ticket: dict) -> None:
        receipt = receipt_for_ticket(ticket, self.settings.tzinfo)
        try:
            self.transport.send(encode(render_lines(receipt, self.settings.paper_width)))
        except Exception as exc:  # any failure is recorded against the ticket
            error = str(exc) or type(exc).__name__
            logger.warning("ticket %s attempt %d failed: %s", ticket["id"], ticket["attempts"], error)
            self._record_failure(ticket, error)
            return
        self.store.mark_sent(ticket["id"])
        logger.info("ticket %s printed", ticket["id"])

    def _record_failure(self, ticket: dict, error: str) -> None:
        if ticket["attempts"] >= self.settings.max_attempts:
            self.store.record_failure(ticket["id"], error, retry_at_ms=None)
            return
        # Exponential backoff: base, 2x base, 4x base, ...
        delay_s = self.settings.retry_base_seconds * 2 ** (ticket["attempts"] - 1)
        self.store.record_failure(ticket["id"], error, retry_at_ms=self.clock() + delay_s * 1000)


class SchedulerThread:
    def __init__(self, scheduler: Scheduler, interval: float) -> None:
        self._scheduler = scheduler
        self._interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="printarr-scheduler", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=10)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._scheduler.run_once()
            except Exception:
                logger.exception("scheduler tick failed")
            self._stop.wait(self._interval)
