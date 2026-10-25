"""Background worker that prints tickets once they are due, with retries."""

from __future__ import annotations

import json
import logging
import threading
import uuid
import time
from datetime import datetime
from collections.abc import Callable

from app.alerts import Notifier
from app.blocks import parse_blocks, unavailable_lines
from app.config import Settings
from app.escpos import CUT_FEED, encode
from app.escpos_image import payload_to_png
from app.ha import HAError, client_from_store
from app.metrics import Metrics
from app.printer import PrinterError, PrintInterrupted, Transport
from app.receipt import Line, render_ticket_lines, sender_label, ticket_feed
from app.status import FAULT_TEXT, PrinterStatus, decode
from app.render.registry import design_line
from app.text import printable
from app import ticket_images
from app.templates import template_by_id
from app.blocks import resolve_blocks
from app.store import PRINT_CODE_LEN, RELEASE_TAG_FOR_TRIGGER, TicketStore, now_ms

# The default briefing's layout: the three metrics and the graph printarr reads at release, set by PUT /api/v1/briefing/default.
DEFAULT_BRIEFING_SETTING = "briefing_default"

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
    """A ticket that leads the piece: a briefing (template 101) or a composed ticket whose first block is a greeting."""
    if int(ticket.get("template_id") or 0) == 101:
        return True
    if int(ticket.get("template_id") or 0) == 103:
        try:
            stored = json.loads(ticket.get("slots_json") or "{}")
        except ValueError:
            return False
        if "preset" in stored:  # the briefing preset always opens with its greeting
            return True
        blocks = stored.get("blocks", [])
        return bool(blocks) and blocks[0].get("type") == "greeting"
    return False


INNER_GAP = 10  # dots between two tickets printed as one piece, the same as between two cards
STAMP_GAP = 24  # dots between the last ticket and the print time and code


def _gap_line(height: int) -> Line:
    return Line("", raster=(64, height, bytes(64 * height)))


def _trim_blank(lines: list[Line], top: bool) -> list[Line]:
    """Drops the all-white rows at the top (or bottom) of a ticket's picture: its margin, which a cut needs and a join does not."""
    order = range(len(lines)) if top else range(len(lines) - 1, -1, -1)
    out = list(lines)
    for i in order:
        line = out[i]
        if line.raster is None:
            break
        width, height, data = line.raster
        rows = [data[r * width:(r + 1) * width] for r in range(height)]
        blank = bytes(width)
        if top:
            while rows and rows[0] == blank:
                rows.pop(0)
        else:
            while rows and rows[-1] == blank:
                rows.pop()
        if rows:
            out[i] = Line(line.text, line.align, line.bold, line.tall, (width, len(rows), b"".join(rows)))
            break
        out[i] = None  # the whole line was margin
    return [line for line in out if line is not None]


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
        lines = ticket_lines(slots, client, template_id=int(ticket["template_id"]), sender=sender_label(ticket), recipient=ticket.get("recipient"))
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

    def _keep_image(self, ticket: dict, payload: bytes | None) -> str | None:
        """Save the bytes sent to the printer as a PNG. Returns the file path, or None when there is none.

        Never raises: a bad image must not hold up the queue or undo a print.
        """
        if payload is None:
            return None
        try:
            png = payload_to_png(payload)
            path = ticket_images.save(self.settings.images_dir, ticket["id"], png, self.settings.image_keep)
            return str(path)
        except Exception:
            logger.exception("ticket %s: could not save its image", ticket["id"])
            return None

    def _ticket_lines(self, ticket: dict) -> list[Line]:
        return render_ticket_lines(ticket, self.settings.tzinfo, self.settings.paper_width, self.live_lines(ticket))

    def _print(self, ticket: dict) -> None:
        payload: bytes | None = None  # kept for the ticket image, also when the send fails
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
            payload = encode(
                lines + self._stamp_lines(ticket["id"][:PRINT_CODE_LEN]),
                feed=ticket_feed(ticket),
                raster_mode=self.settings.raster_mode,
            )
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
            image = self._keep_image(ticket, payload)
            logger.warning(
                "ticket %s attempt %d failed: %s (image: %s)",
                ticket["id"], ticket["attempts"], error, image or "none",
            )
            self.metrics.incr("print_failures")
            if isinstance(exc, PrintInterrupted):
                self.metrics.incr("print_interrupted")
            if isinstance(exc, PrinterError) and self.notifier:
                self.notifier.problem("printer", f"printer unreachable: {error}")
            self._record_failure(ticket, error)
            return
        if self.notifier:
            self.notifier.recovered("printer", "printer is reachable again")
        self._keep_image(ticket, payload)
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

        A morning or evening release prints the tickets tagged for it (and any), so a briefing queued for
        the other release stays in the pile. A request prints the whole pile. A morning or evening release
        with no briefing queued for it prints the default briefing first, when one is set.

        A strip is cut after strip_max_blocks tickets. Tickets are claimed before printing, so a repeat
        release prints nothing new. A failed print puts its claimed tickets back on hold. If a later
        strip fails, ReleaseIncomplete carries the strips already printed, so the caller can report them.
        """
        tag = RELEASE_TAG_FOR_TRIGGER.get(trigger)
        if tag is not None:
            self._ensure_default_briefing(person, tag)
        pile = self.store.pile(person, tag)
        lead = next((t for t in pile if opens_strip(t)), None)
        if lead is not None:  # the first briefing leads the piece, everything else follows in queue order
            pile = [lead] + [t for t in pile if t is not lead]
        strips: list[dict] = []
        for chunk in self._strip_chunks(pile):
            won = self.store.claim([ticket["id"] for ticket in chunk])
            if not won:
                continue
            tickets = [t for t in (self.store.get(ticket_id) for ticket_id in won) if t is not None]
            strip_id = uuid.uuid4().hex
            parts: list[list[Line]] = []
            try:
                parts = [self._ticket_lines(ticket) for ticket in tickets]
                lines = self._strip_lines(parts) + self._stamp_lines(strip_id[:PRINT_CODE_LEN])
                strip_payload = encode(lines, feed=CUT_FEED, raster_mode=self.settings.raster_mode)
                self.transport.send(strip_payload)
            except Exception as exc:
                self.store.unclaim(won)
                # Each ticket in the failed strip keeps its own image, drawn as its own ticket.
                for ticket, part in zip(tickets, parts):
                    image = self._keep_image(ticket, self._ticket_payload(part, ticket))
                    logger.warning("ticket %s in failed strip %s (image: %s)", ticket["id"], strip_id, image or "none")
                raise ReleaseIncomplete(strips, str(exc) or type(exc).__name__) from exc
            self._keep_strip_image(tickets, strip_payload)  # every ticket in the piece recalls the whole piece
            for ticket_id in won:
                self._mark_sent(ticket_id, strip_id=strip_id, strip_trigger=trigger)
            logger.info("strip %s for %s (%s): %d ticket(s) printed", strip_id, person, trigger, len(won))
            strips.append({"strip_id": strip_id, "ticket_ids": won})
        return strips

    def _ensure_default_briefing(self, person: str, tag: str) -> None:
        """Queue the default briefing for this release, when none is waiting for it and none was built today.

        The ticket holds only the layout. Its values are read when it prints, so an unreachable Home Assistant
        prints the metrics with their placeholder mark. Never raises: a release still prints the rest of the pile.
        """
        try:
            raw = self.store.get_setting(DEFAULT_BRIEFING_SETTING)
            if not raw:
                return
            if any(opens_strip(t) and t["release_on"] == tag for t in self.store.pile(person, tag)):
                return
            day = datetime.now(self.settings.tzinfo).strftime("%Y-%m-%d")
            key = f"default:{person}:{tag}:{day}"
            if self.store.get_by_key(key) is not None:  # built today already: printed, or waiting in the pile
                return
            layout = json.loads(raw)
            slots = {"preset": "briefing", "default": True, "slots": {"time_of_day": tag, **layout}}
            self.store.create(
                recipient=person,
                message=f"Default {tag} briefing",
                send_at_ms=self.clock(),
                template_id=103,
                decorations=(),
                selection="rule",
                choice_source="rule",
                kind=tag,
                slots_json=json.dumps(slots),
                held=True,
                delivery="on_release",
                idempotency_key=key,
                release_on=tag,
            )
            logger.info("default %s briefing queued for %s (%s)", tag, person, key)
        except Exception:
            logger.exception("could not queue the default %s briefing for %s", tag, person)

    def _stamp_lines(self, code: str) -> list[Line]:
        """The print time and short code, in small text below the last ticket, inside the space fed for the cut.

        It is text for the printer, never part of a ticket's picture."""
        stamp = datetime.now(self.settings.tzinfo).strftime("%Y-%m-%d %H:%M")
        return [_gap_line(STAMP_GAP), Line(f"{stamp}  {code}", align="center")]

    def _keep_strip_image(self, tickets: list[dict], payload: bytes) -> None:
        """Save the printed piece as the image of each ticket on it, so GET /tickets/{id}/image shows the whole strip.

        Never raises, like _keep_image.
        """
        try:
            png = payload_to_png(payload)
            for ticket in tickets:
                ticket_images.save(self.settings.images_dir, ticket["id"], png, self.settings.image_keep)
        except Exception:
            logger.exception("strip of %d ticket(s): could not save its image", len(tickets))

    def _strip_chunks(self, pile: list[dict]) -> list[list[dict]]:
        """Splits a pile into strips: one piece of paper, new only when strip_max_blocks tickets are on it. A greeting ticket leads (the pile is ordered that way); a second one is just another tile."""
        size = max(1, self.settings.strip_max_blocks)
        chunks: list[list[dict]] = []
        current: list[dict] = []
        for ticket in pile:
            if current and len(current) >= size:
                chunks.append(current)
                current = []
            current.append(ticket)
        if current:
            chunks.append(current)
        return chunks

    def _ticket_payload(self, lines: list[Line], ticket: dict) -> bytes:
        """The bytes for one ticket on its own, as its image is drawn. A strip adds margins around the tickets."""
        return encode(lines, feed=ticket_feed(ticket), raster_mode=self.settings.raster_mode)

    def _strip_lines(self, parts: list[list[Line]]) -> list[Line]:
        """The tickets one after another as one piece of paper. Each ticket was drawn with its own top and bottom
        margin; those are for a cut, so only the first top and the last bottom stay, and the tickets in between
        are one card gap apart. Blank space around each strip comes from the shell, not from here."""
        margin = self.settings.strip_margin_dots
        blank = Line("", raster=(64, margin, bytes(64 * margin))) if margin > 0 else None
        lines: list[Line] = [blank] if blank else []
        last = len(parts) - 1
        for i, part in enumerate(parts):
            part = list(part)
            if i > 0:
                part = _trim_blank(part, top=True)
                part.insert(0, _gap_line(INNER_GAP))
            if i < last:
                part = _trim_blank(part, top=False)
            lines += part
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
