"""Background worker that prints tickets once they are due, with retries."""

from __future__ import annotations

import json
import logging
import threading
import uuid
import time
from collections.abc import Callable

from app.alerts import Notifier
from app.blocks import parse_blocks, unavailable_lines
from app.config import Settings
from app.escpos import encode
from app.ha import HAError, client_from_store
from app.metrics import Metrics
from app.printer import PrinterError, PrintInterrupted, Transport
from app.receipt import Line, render_ticket_lines, sender_label, ticket_feed
from app.status import FAULT_TEXT, PrinterStatus, decode
from app.render.registry import design_line
from app.text import printable
from app.templates import template_by_id
from app.blocks import resolve_blocks
from app.store import TicketStore, now_ms

logger = logging.getLogger("printarr.scheduler")


BATCH_SIZE = 10
SLOW_TICKET_MS = 10_000  # the target: always under 10 s
MARK_SENT_TRIES = 3
MARK_SENT_RETRY_S = 0.2


class ReleaseIncomplete(PrinterError):
    """A person's release stopped part-way. `strips` are the strips already printed and recorded."""

    def __init__(self, strips: list[dict], error: str) -> None:
        super().__init__(error)
        self.strips = strips


def opens_strip(ticket: dict) -> bool:
    """A greeting always starts a new strip: a briefing (template 101) or a composed ticket whose first block is a greeting."""
    if int(ticket.get("template_id") or 0) == 101:
        return True
    if int(ticket.get("template_id") or 0) == 103:
        try:
            blocks = json.loads(ticket.get("slots_json") or "{}").get("blocks", [])
        except ValueError:
            return False
        return bool(blocks) and blocks[0].get("type") == "greeting"
    return False


class Scheduler:
    def __init__(
        self,
        store: TicketStore,
        transport: Transport,
        settings: Settings,
        clock: Callable[[], int] = now_ms,
        notifier: Notifier | None = None,
        metrics: Metrics | None = None,
        printer_waiting: Callable[[], bool] | None = None,
    ) -> None:
        self.store = store
        self.transport = transport
        self.settings = settings
        # True until setup is finished and a printer address is saved. No status polling until then.
        self._printer_waiting = printer_waiting
        self.clock = clock
        self.notifier = notifier
        self.metrics = metrics or Metrics()
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
        if self._printer_waiting is not None and self._printer_waiting():
            self._last_status = None
            return False
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
            self.metrics.incr("queue_pauses")
            self._paused_reason = reason
        return True

    def live_lines(self, ticket: dict) -> list[Line]:
        """Fetch Home Assistant data now, so a held or scheduled ticket prints current values."""
        template = template_by_id(int(ticket["template_id"]))
        if template.design:
            return self.design_lines(ticket, template.design)
        if template.group == "slots":
            return self.slot_lines_live(ticket)
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

    def slot_lines_live(self, ticket: dict) -> list[Line]:
        """Lay out a slot ticket, reading its Home Assistant metrics now. Missing values print --."""
        from app.compose import ticket_lines  # imported here: app.compose imports app.receipt

        slots = json.loads(ticket.get("slots_json") or "{}")
        try:
            client = client_from_store(self.store)
        except HAError:
            client = None
        lines = ticket_lines(slots, client, template_id=int(ticket["template_id"]), sender=sender_label(ticket))
        blocks = parse_blocks(ticket.get("blocks_json"))
        if not blocks:
            return lines
        try:
            return lines + resolve_blocks(blocks, client)
        except HAError as exc:
            logger.warning("ticket %s: Home Assistant unavailable at print time: %s", ticket["id"], exc)
            return lines + unavailable_lines(blocks)

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
            glyph_sources = [line.text for line in lines if line.text and printable(line.text)[1]]
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
            self.metrics.incr("print_failures")
            if isinstance(exc, PrintInterrupted):
                self.metrics.incr("print_interrupted")
            if isinstance(exc, PrinterError) and self.notifier:
                self.notifier.problem("printer", f"printer unreachable: {error}")
            self._record_failure(ticket, error)
            return
        if self.notifier:
            self.notifier.recovered("printer", "printer is reachable again")
        self.metrics.incr("tickets_printed")
        self._mark_sent(ticket["id"], print_ms=round(total_ms))
        logger.info("ticket %s printed", ticket["id"])

    def _mark_sent(self, ticket_id: str, **fields) -> None:
        """Record a printed ticket. The paper is already out, so a database hiccup is retried, not raised.

        If every try fails the ticket stays 'printing' and is failed at the next restart, rather than
        being printed again.
        """
        for attempt in range(1, MARK_SENT_TRIES + 1):
            try:
                self.store.mark_sent(ticket_id, **fields)
                return
            except Exception:
                if attempt == MARK_SENT_TRIES:
                    logger.exception("ticket %s printed but could not be marked sent", ticket_id)
                    self.metrics.incr("mark_sent_failures")
                    return
                time.sleep(MARK_SENT_RETRY_S * attempt)

    def print_release(self, person: str, trigger: str) -> list[dict]:
        """Print one person's pile as strips. Each strip holds only this person's tickets and is cut after it.

        A strip is cut after strip_max_blocks tickets. Tickets are claimed before printing, so a repeat
        release prints nothing new. A failed print puts its claimed tickets back on hold. If a later
        strip fails, ReleaseIncomplete carries the strips already printed, so the caller can report them.
        """
        pile = self.store.pile(person)
        strips: list[dict] = []
        for chunk in self._strip_chunks(pile):
            won = self.store.claim([ticket["id"] for ticket in chunk])
            if not won:
                continue
            tickets = [self.store.get(ticket_id) for ticket_id in won]
            strip_id = uuid.uuid4().hex
            try:
                lines = self._strip_lines([t for t in tickets if t is not None])
                self.transport.send(encode(lines, feed=1, raster_mode=self.settings.raster_mode))
            except Exception as exc:
                self.store.unclaim(won)
                raise ReleaseIncomplete(strips, str(exc) or type(exc).__name__) from exc
            for ticket_id in won:
                self._mark_sent(ticket_id, strip_id=strip_id, strip_trigger=trigger)
            logger.info("strip %s for %s (%s): %d ticket(s) printed", strip_id, person, trigger, len(won))
            strips.append({"strip_id": strip_id, "ticket_ids": won})
        return strips

    def _strip_chunks(self, pile: list[dict]) -> list[list[dict]]:
        """Splits a pile into strips: at most strip_max_blocks tickets, and a greeting starts a new strip."""
        size = max(1, self.settings.strip_max_blocks)
        chunks: list[list[dict]] = []
        current: list[dict] = []
        for ticket in pile:
            if current and (len(current) >= size or opens_strip(ticket)):
                chunks.append(current)
                current = []
            current.append(ticket)
        if current:
            chunks.append(current)
        return chunks

    def _strip_lines(self, tickets: list[dict]) -> list[Line]:
        """The tickets one after another. Blank space around each strip comes from the shell, not from here."""
        margin = self.settings.strip_margin_dots
        blank = Line("", raster=(64, margin, bytes(64 * margin))) if margin > 0 else None
        lines: list[Line] = [blank] if blank else []
        for ticket in tickets:
            lines += render_ticket_lines(ticket, self.settings.tzinfo, self.settings.paper_width, self.live_lines(ticket))
        if blank:
            lines.append(blank)
        return lines

    def _record_failure(self, ticket: dict, error: str) -> None:
        if ticket["attempts"] >= self.settings.max_attempts:
            self.metrics.incr("tickets_dead_lettered")
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
