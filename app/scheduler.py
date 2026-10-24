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
from app.receipt import Line, render_ticket_lines, ticket_feed
from app.status import FAULT_TEXT, PrinterStatus, decode
from app.render.registry import design_line
from app.text import printable
from app.templates import template_by_id
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
        self._paused_reason: str | None = None
        self._last_status_ms: int | None = None
        self._last_status: PrinterStatus | None = None

    @property
    def paused_reason(self) -> str | None:
        """Why the queue is waiting, or None when it is printing normally."""
        return self._paused_reason

    def run_once(self) -> int:
        """Print every ticket that is due right now. Returns how many were attempted."""
        now = self.clock()
        if self.store.count_due(now) == 0:
            return 0
        if self._blocked_by_printer(now):
            return 0
        jobs = self.store.claim_due(now, BATCH_SIZE)
        for ticket in jobs:
            self._print(ticket)
        return len(jobs)

    def _blocked_by_printer(self, now: int) -> bool:
        """Hold the queue while the printer reports a fault, and resume when it clears.

        Status is read at most once per poll interval. A printer that cannot be reached is
        not a pause: the send fails and the ticket backs off as usual.
        """
        if self._last_status_ms is None or now - self._last_status_ms >= self.settings.poll_interval * 1000:
            self._last_status_ms = now
            try:
                self._last_status = decode(self.transport.read_status())
            except PrinterError:
                self._last_status = None
        status = self._last_status
        if status is None or not status.blocking:
            if self._paused_reason is not None:
                logger.info("printer ready again, resuming queue (was: %s)", self._paused_reason)
                self._paused_reason = None
            return False
        reason = ", ".join(sorted(FAULT_TEXT[key] for key in status.faults))
        if reason != self._paused_reason:
            logger.warning("queue paused: %s", reason)
            self._paused_reason = reason
        return True

    def live_lines(self, ticket: dict) -> list[Line]:
        """Fetch Home Assistant data now, so a held or scheduled ticket prints current values."""
        template = template_by_id(int(ticket["template_id"]))
        if template.design:
            return self.design_lines(ticket, template.design)
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

    def design_lines(self, ticket: dict, design: str) -> list[Line]:
        """Draw an image design with the entities read now. Missing values print NO DATA."""
        client = client_from_store(self.store)
        line, all_missing = design_line(design, ticket["message"], client)
        if client is not None and self.notifier:
            if all_missing:
                self.notifier.problem("home_assistant", "Home Assistant gave no values for a design ticket")
            else:
                self.notifier.recovered("home_assistant", "Home Assistant answers again")
        return [line]

    def _print(self, ticket: dict) -> None:
        try:
            started = time.perf_counter()
            live = self.live_lines(ticket)
            fetched = time.perf_counter()
            lines = render_ticket_lines(ticket, self.settings.tzinfo, self.settings.paper_width, live)
            # Lines drawn as images (names outside CP437): log the source text, so the printed
            # bitmap can be matched to what was sent.
            glyph_sources = [line.text for line in lines if line.raster is None and printable(line.text)[1]]
            if glyph_sources:
                logger.info("ticket %s: %d line(s) drawn as images: %s", ticket["id"], len(glyph_sources), glyph_sources)
            payload = encode(lines, feed=ticket_feed(ticket), raster_mode=self.settings.raster_mode)
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
        self.store.mark_sent(ticket["id"], print_ms=round(total_ms))
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
