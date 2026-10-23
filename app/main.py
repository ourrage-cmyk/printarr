"""HTTP API for queueing receipt tickets, previewing them and checking the printer.

The API is the only component that talks to the printer. Clients send plain text and
the API renders it into the printer's byte stream.
"""

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
from app.receipt import Receipt, render_lines, render_ticket_lines
from app.scheduler import Scheduler, SchedulerThread
from app.store import TicketNotFound, TicketStateError, TicketStore, now_ms
from app.templates import (
    DECORATIONS,
    RECIPIENTS,
    TEMPLATES,
    Choice,
    OpenAICompatibleModel,
    Recipient,
    resolve_choice,
)

logging.basicConfig(level=os.environ.get("PRINTARR_LOG_LEVEL", "INFO"))
logger = logging.getLogger("printarr")

Status = Literal["pending", "printing", "sent", "failed", "cancelled"]
T = TypeVar("T")

API_DESCRIPTION = """
Queue receipt tickets for the Epson TM-T88V. Clients send plain text. The API picks a
template for the recipient, renders the receipt, and prints it when it is due.

There is no authentication. Run it on the home LAN only.

Template choice: pass `template` to pick one explicitly from that recipient's group.
If you leave it out, a local decision model picks one when it is configured. Otherwise
a fixed rule picks one.
"""


class TicketCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    recipient: Recipient = Field(description="A fixed recipient: yannic or wife.")
    message: str = Field(min_length=1, max_length=2000)
    title: str | None = Field(default=None, max_length=80, examples=["Dinner"])
    sender: str | None = Field(
        default=None,
        max_length=40,
        description="Who asked for the ticket, for the log. For example home-assistant or hermes.",
        examples=["home-assistant"],
    )
    template: int | None = Field(
        default=None,
        ge=1,
        description="Template id from GET /api/v1/templates. Must belong to the recipient's group.",
    )
    send_at: datetime | None = Field(
        default=None,
        description=(
            "When to print, as ISO 8601. Values without a timezone use the server's "
            "PRINTARR_TIMEZONE. Omit to print as soon as possible."
        ),
        examples=["2026-10-24T17:30:00"],
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
    template_id: int
    decorations: list[str]
    selection: Literal["explicit", "model", "rule"]
    created_at: datetime
    updated_at: datetime
    printed_at: datetime | None


class ChoiceOut(BaseModel):
    template_id: int
    decorations: list[str]
    selection: Literal["explicit", "model", "rule"]


class PreviewOut(ChoiceOut):
    text: str = Field(description="The receipt as it would be printed, as plain text.")
    width: int


class TemplateOut(BaseModel):
    id: int
    name: str
    recipient: str
    title_align: Literal["left", "center"]
    tall_title: bool
    rule: str
    optional_decorations: list[str]
    default_decorations: list[str]


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


def _choice_out(choice: Choice) -> ChoiceOut:
    return ChoiceOut(
        template_id=choice.template.id,
        decorations=list(choice.decorations),
        selection=choice.selection,
    )


def create_app(settings: Settings | None = None, transport: Transport | None = None) -> FastAPI:
    settings = settings or load_settings()
    transport = transport or build_transport(settings)
    store = TicketStore(settings.db_path)
    model = (
        OpenAICompatibleModel(settings.llm_base_url, settings.llm_model, settings.llm_timeout)
        if settings.llm_enabled and settings.llm_base_url
        else None
    )
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
        version="0.2.0",
        description=API_DESCRIPTION,
        lifespan=lifespan,
    )
    app.state.scheduler = scheduler

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

    def choose(body: TicketCreate) -> Choice:
        try:
            return resolve_choice(body.recipient, body.title, body.message, body.template, model)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None

    def render_preview(body: TicketCreate, choice: Choice) -> str:
        receipt = Receipt(
            recipient=RECIPIENTS[body.recipient],
            sender=body.sender,
            title=body.title,
            message=body.message,
            sent_at=datetime.fromtimestamp(_resolve_send_at(body.send_at, settings.tzinfo) / 1000, tz=settings.tzinfo),
        )
        lines = render_lines(receipt, width, choice.template, choice.decorations)
        return to_text(lines, width)

    @app.get("/healthz", tags=["meta"])
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @api.get("/templates", response_model=list[TemplateOut], tags=["templates"])
    def list_templates() -> list[dict[str, Any]]:
        return [
            {
                "id": t.id,
                "name": t.name,
                "recipient": t.group,
                "title_align": t.title_align,
                "tall_title": t.tall_title,
                "rule": t.rule,
                "optional_decorations": list(t.allowed),
                "default_decorations": list(t.default),
            }
            for t in TEMPLATES
        ]

    @api.post("/tickets", status_code=201, response_model=TicketOut, tags=["tickets"])
    def create_ticket(body: TicketCreate) -> dict[str, Any]:
        choice = choose(body)
        return store.create(
            recipient=body.recipient,
            message=body.message,
            sender=body.sender,
            title=body.title,
            send_at_ms=_resolve_send_at(body.send_at, settings.tzinfo),
            template_id=choice.template.id,
            decorations=choice.decorations,
            selection=choice.selection,
        )

    @api.get("/tickets", response_model=list[TicketOut], tags=["tickets"])
    def list_tickets(
        status: Status | None = None,
        recipient: Recipient | None = None,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ) -> list[dict[str, Any]]:
        return store.search(status=status, recipient=recipient, limit=limit, offset=offset)

    @api.post("/tickets/preview", response_model=PreviewOut, tags=["tickets"])
    def preview(body: TicketCreate) -> dict[str, Any]:
        """Choose a template and render a receipt without queueing it."""
        choice = choose(body)
        return {
            **_choice_out(choice).model_dump(),
            "text": render_preview(body, choice),
            "width": width,
        }

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

    @api.get("/tickets/{ticket_id}/preview", response_class=PlainTextResponse, tags=["tickets"])
    def ticket_preview(ticket_id: str) -> str:
        ticket = ticket_or_404(ticket_id)
        return to_text(render_ticket_lines(ticket, settings.tzinfo, width), width)

    @api.get(
        "/tickets/{ticket_id}/escpos",
        response_class=Response,
        tags=["tickets"],
        responses={200: {"content": {"application/octet-stream": {}}}},
    )
    def ticket_escpos(ticket_id: str) -> Response:
        """The exact ESC/POS byte stream for this ticket. The simulator reads this."""
        ticket = ticket_or_404(ticket_id)
        data = encode(render_ticket_lines(ticket, settings.tzinfo, width))
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
            sender="printarr",
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

__all__ = ["DECORATIONS", "app", "create_app"]
