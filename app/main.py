"""HTTP API for queueing receipt tickets, previewing them and checking the printer."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Literal, TypeVar

from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from app.config import Settings, load_settings
from app.escpos import encode, to_text
from app.printer import PrinterError, Transport, build_transport
from app.receipt import Receipt, receipt_for_ticket, render_lines
from app.scheduler import Scheduler, SchedulerThread
from app.store import TicketNotFound, TicketStateError, TicketStore, now_ms

logging.basicConfig(level=os.environ.get("PRINTARR_LOG_LEVEL", "INFO"))
logger = logging.getLogger("printarr")

Status = Literal["pending", "printing", "sent", "failed", "cancelled"]
T = TypeVar("T")

API_DESCRIPTION = """
Queue receipt tickets for the Epson TM-T88V. Each ticket has a recipient and a
message, and an optional send time. Tickets are stored in SQLite and printed by a
background scheduler once they are due. Failed prints are retried with backoff.
"""


class TicketCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    recipient: str = Field(min_length=1, max_length=40, examples=["Anna"])
    message: str = Field(min_length=1, max_length=2000)
    sender: str | None = Field(
        default=None,
        max_length=40,
        description="Who asked for the ticket, for the log. For example home-assistant or hermes.",
        examples=["home-assistant"],
    )
    title: str | None = Field(default=None, max_length=80, examples=["Dinner"])
    send_at: datetime | None = Field(
        default=None,
        description=(
            "When to print, as ISO 8601. Values without a timezone use the server's "
            "PRINTARR_TIMEZONE. Omit to print as soon as possible."
        ),
        examples=["2026-10-24T19:00:00"],
    )


class TicketOut(BaseModel):
    id: str
    recipient: str
    sender: str | None
    title: str | None
    message: str
    status: Status
    send_at: datetime
    next_attempt_at: datetime
    attempts: int
    last_error: str | None
    created_at: datetime
    updated_at: datetime
    printed_at: datetime | None


class PreviewOut(BaseModel):
    text: str = Field(description="The receipt as it would be printed, as plain text.")
    width: int


class PrinterStatus(BaseModel):
    mode: str
    target: str
    reachable: bool
    error: str | None = None


def _resolve_send_at(value: datetime | None, tz: Any) -> int:
    if value is None:
        return now_ms()
    if value.tzinfo is None:
        value = value.replace(tzinfo=tz)
    return int(value.timestamp() * 1000)


def create_app(settings: Settings | None = None, transport: Transport | None = None) -> FastAPI:
    settings = settings or load_settings()
    transport = transport or build_transport(settings)
    store = TicketStore(settings.db_path)
    scheduler = Scheduler(store, transport, settings)
    width = settings.paper_width

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        store.init()
        recovered = store.recover_interrupted()
        if recovered:
            logger.warning("re-queued %d ticket(s) interrupted by a restart", recovered)
        worker = (
            SchedulerThread(scheduler, settings.poll_interval)
            if settings.scheduler_enabled
            else None
        )
        if worker:
            worker.start()
        try:
            yield
        finally:
            if worker:
                worker.stop()

    app = FastAPI(
        title="Printarr",
        version="0.1.0",
        description=API_DESCRIPTION,
        lifespan=lifespan,
    )
    app.state.scheduler = scheduler

    # No authentication: this is a LAN-only service, and any client on the network may call it.
    api = APIRouter(prefix="/api/v1")

    def ticket_or_404(ticket_id: str) -> dict[str, Any]:
        ticket = store.get(ticket_id)
        if ticket is None:
            raise HTTPException(status_code=404, detail="ticket not found")
        return ticket

    def guarded(action: Callable[[str], T], ticket_id: str) -> T:
        try:
            return action(ticket_id)
        except TicketNotFound:
            raise HTTPException(status_code=404, detail="ticket not found") from None
        except TicketStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    def preview_receipt(body: TicketCreate) -> Receipt:
        sent_at_ms = _resolve_send_at(body.send_at, settings.tzinfo)
        return receipt_for_ticket(
            {
                "recipient": body.recipient,
                "sender": body.sender,
                "title": body.title,
                "message": body.message,
                "send_at_ms": sent_at_ms,
            },
            settings.tzinfo,
        )

    @app.get("/healthz", tags=["meta"])
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @api.post("/tickets", status_code=201, response_model=TicketOut, tags=["tickets"])
    def create_ticket(body: TicketCreate) -> dict[str, Any]:
        return store.create(
            recipient=body.recipient,
            message=body.message,
            sender=body.sender,
            title=body.title,
            send_at_ms=_resolve_send_at(body.send_at, settings.tzinfo),
        )

    @api.get("/tickets", response_model=list[TicketOut], tags=["tickets"])
    def list_tickets(
        status: Status | None = None,
        recipient: str | None = None,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ) -> list[dict[str, Any]]:
        return store.search(status=status, recipient=recipient, limit=limit, offset=offset)

    @api.post("/tickets/preview", response_model=PreviewOut, tags=["tickets"])
    def preview(body: TicketCreate) -> PreviewOut:
        """Render a receipt without queueing it."""
        text = to_text(render_lines(preview_receipt(body), width), width)
        return PreviewOut(text=text, width=width)

    @api.get("/tickets/{ticket_id}", response_model=TicketOut, tags=["tickets"])
    def get_ticket(ticket_id: str) -> dict[str, Any]:
        return ticket_or_404(ticket_id)

    @api.post("/tickets/{ticket_id}/cancel", response_model=TicketOut, tags=["tickets"])
    def cancel_ticket(ticket_id: str) -> dict[str, Any]:
        """Cancel a ticket that has not been printed yet."""
        return guarded(store.cancel, ticket_id)

    @api.post("/tickets/{ticket_id}/retry", response_model=TicketOut, tags=["tickets"])
    def retry_ticket(ticket_id: str) -> dict[str, Any]:
        """Queue a failed or cancelled ticket again, to print now."""
        return guarded(store.requeue, ticket_id)

    @api.get(
        "/tickets/{ticket_id}/preview",
        response_class=PlainTextResponse,
        tags=["tickets"],
    )
    def ticket_preview(ticket_id: str) -> str:
        ticket = ticket_or_404(ticket_id)
        return to_text(render_lines(receipt_for_ticket(ticket, settings.tzinfo), width), width)

    @api.get(
        "/tickets/{ticket_id}/escpos",
        response_class=Response,
        tags=["tickets"],
        responses={200: {"content": {"application/octet-stream": {}}}},
    )
    def ticket_escpos(ticket_id: str) -> Response:
        """The exact ESC/POS byte stream for this ticket. The simulator reads this."""
        ticket = ticket_or_404(ticket_id)
        data = encode(render_lines(receipt_for_ticket(ticket, settings.tzinfo), width))
        return Response(content=data, media_type="application/octet-stream")

    @api.get("/printer", response_model=PrinterStatus, tags=["printer"])
    def printer_status() -> PrinterStatus:
        try:
            transport.check()
        except PrinterError as exc:
            return PrinterStatus(
                mode=settings.printer_mode, target=transport.target, reachable=False, error=str(exc)
            )
        return PrinterStatus(mode=settings.printer_mode, target=transport.target, reachable=True)

    @api.post("/printer/test", response_model=PrinterStatus, tags=["printer"])
    def printer_test() -> PrinterStatus:
        """Print a test receipt right away. Returns 502 if the printer is unreachable."""
        receipt = Receipt(
            recipient="Test",
            sender="Printarr",
            title="Printer test",
            message="If you can read this, the printer is connected.",
            sent_at=datetime.now(settings.tzinfo),
        )
        try:
            transport.send(encode(render_lines(receipt, width)))
        except PrinterError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from None
        return PrinterStatus(mode=settings.printer_mode, target=transport.target, reachable=True)

    app.include_router(api)
    return app


app = create_app()
