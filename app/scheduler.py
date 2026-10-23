"""Background worker that prints tickets once they are due, with retries."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from app.alerts import Notifier
from app.blocks import parse_blocks, unavailable_lines
from app.config import Settings
from app.escpos import encode
from app.ha import HAError, client_from_store
from app.printer import PrinterError, Transport
from app.receipt import Line, render_ticket_lines
from app.blocks import resolve_blocks
from app.store import TicketStore, now_ms

logger = logging.getLogger("printarr.scheduler")


BATCH_SIZE = 10
SLOW_TICKET_MS = 10_000  # the target: always under 10 s


class Scheduler:
    def __init__(
        self,
        store: TicketStore,
        transport: Transport,
        settings: Settings,
        clock: Callable[[], int] = now_ms,
        notifier: Notifier | None = None,
    ) -> None:
        self.store = store
        self.transport = transport
        self.settings = settings
        self.clock = clock
        self.notifier = notifier

    def run_once(self) -> int:
        """Print every ticket that is due right now. Returns how many were attempted."""
        jobs = self.store.claim_due(self.clock(), BATCH_SIZE)
        for ticket in jobs:
            self._print(ticket)
        return len(jobs)

    def live_lines(self, ticket: dict) -> list[Line]:
        """Fetch Home Assistant data now, so a held or scheduled ticket prints current values."""
        blocks = parse_blocks(ticket.get("blocks_json"))
        if not blocks:
            return []
        try:
            lines = resolve_blocks(blocks, client_from_store(self.store))
        except HAError as exc:
            # Print what we can, with a clear placeholder, rather than drop the ticket.
            logger.warning("ticket %s: Home Assistant unavailable at print time: %s", ticket["id"], exc)
            if self.notifier:
                self.notifier.problem("home_assistant", f"Home Assistant unavailable at print time: {exc}")
            return unavailable_lines(blocks)
        if self.notifier:
            self.notifier.recovered("home_assistant", "Home Assistant answers again")
        return lines

    def _print(self, ticket: dict) -> None:
        try:
            started = time.perf_counter()
            live = self.live_lines(ticket)
            fetched = time.perf_counter()
            lines = render_ticket_lines(ticket, self.settings.tzinfo, self.settings.paper_width, live)
            payload = encode(lines)
            rendered = time.perf_counter()
            self.transport.send(payload)
            sent = time.perf_counter()
            total_ms = (sent - started) * 1000
            timing = (
                "ticket %s timing: data %.0f ms, render %.0f ms, send %.0f ms, total %.0f ms"
                % (ticket["id"], (fetched - started) * 1000, (rendered - fetched) * 1000,
                   (sent - rendered) * 1000, total_ms)
            )
            if total_ms > SLOW_TICKET_MS:
                logger.warning("%s (over the %d s target)", timing, SLOW_TICKET_MS // 1000)
            else:
                logger.info(timing)
        except Exception as exc:  # any failure is recorded against the ticket
            error = str(exc) or type(exc).__name__
            logger.warning("ticket %s attempt %d failed: %s", ticket["id"], ticket["attempts"], error)
            if isinstance(exc, PrinterError) and self.notifier:
                self.notifier.problem("printer", f"printer unreachable: {error}")
            self._record_failure(ticket, error)
            return
        if self.notifier:
            self.notifier.recovered("printer", "printer is reachable again")
        self.store.mark_sent(ticket["id"])
        logger.info("ticket %s printed", ticket["id"])

    def _record_failure(self, ticket: dict, error: str) -> None:
        if ticket["attempts"] >= self.settings.max_attempts:
            self.store.record_failure(ticket["id"], error, retry_at_ms=None)
            if self.notifier:
                self.notifier.problem(
                    f"ticket:{ticket['id']}",
                    f"ticket {ticket['id']} for {ticket['recipient']} failed after "
                    f"{ticket['attempts']} attempts: {error}",
                )
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
