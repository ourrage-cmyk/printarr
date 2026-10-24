"""HTTP API for queueing receipt tickets, previewing them and checking the printer.

The API is the only component that talks to the printer. Clients send plain text and
the API renders it into the printer's byte stream.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime
from typing import Any, Literal, TypeVar

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request
from starlette.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from app.web import WEB_UI

from app.alerts import AlertSettings, HeartbeatThread, Notifier, send_telegram
from app.backup import BackupError, NightlyBackup, NightlyThread, import_bytes
from app.config import Settings, load_settings
from app.insights import InsightCache, collect
from app.escpos import encode, to_text
from app.kinds import DEFAULT_KIND, DEFAULT_TONE, KINDS, TONES
from app.printer import PrinterError, Transport, build_transport
from app.metrics import Metrics
from app.status import FAULT_TEXT, REQUESTS_FOR_KEY, decode
from app.receipt import Line, Receipt, line_to_dict, render_lines, render_ticket_lines, ticket_feed
from app.render.registry import design_line, placeholder_line
from app.blocks import Block, resolve_blocks
from app.ha import HAClient, HAError
from app.scheduler import Scheduler, SchedulerThread
from app.store import TicketNotFound, TicketStateError, TicketStore, now_ms
from app.text import printed_as_question
from app.compose import (
    BLOCKS as compose_blocks,
    BlockProblem,
    catalogue as compose_catalogue,
    block_schema as compose_block_schema,
    compose_lines,
    validate_blocks as compose_validate,
)
from app.slots import (
    BRIEFING,
    SLOT_NAMES,
    SlotProblems,
    autofill,
    is_slot_template,
    slot_lines,
)
from app.slots import schema as slot_schema
from app.slots import validate as validate_slots
from app.templates import (
    RECIPIENTS,
    TEMPLATES,
    Choice,
    template_by_id,
    OpenAICompatibleModel,
    SystemOneModel,
    Recipient,
    resolve_choice,
)

logging.basicConfig(level=os.environ.get("PRINTARR_LOG_LEVEL", "INFO"))
logger = logging.getLogger("printarr")

Status = Literal["held", "pending", "printing", "sent", "failed", "cancelled"]
SETTING_KEYS = {
    "enabled": "llm_enabled",
    "base_url": "llm_base_url",
    "model": "llm_model",
    "text_model": "llm_text_model",
    "timeout": "llm_timeout",
}
T = TypeVar("T")


API_DESCRIPTION = """
Queue receipt tickets for the Epson TM-T88V. Clients send plain text. The API picks a
template for the recipient, renders the receipt, and prints it when it is due.

There is no authentication. Run it on the home LAN only.

Template choice: pass `template` to pick one explicitly from that recipient's group.
If you leave it out, a local decision model picks one when it is configured. Otherwise
a fixed rule picks one.
"""


class ComposeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    recipient: Recipient
    blocks: list[dict[str, Any]] = Field(
        min_length=1,
        max_length=16,
        description="Ordered blocks, each {type, mood, slots}. See GET /api/v1/blocks for types and moods.",
    )
    kind: Literal[KINDS] | None = None  # type: ignore[valid-type]
    tone: Literal[TONES] | None = None  # type: ignore[valid-type]
    from_user: Recipient | None = None
    to_user: Recipient | None = None
    sender: str | None = Field(default=None, max_length=40)
    send_at: datetime | None = None
    delivery: Literal["now", "at", "on_release"] | None = None
    hold: bool = False
    hold_key: str | None = Field(default=None, max_length=40)
    idempotency_key: str | None = Field(default=None, max_length=120)


class PersonRelease(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trigger: Literal["morning", "evening", "arrival", "request"] = Field(
        default="request", description="Why the strip is printed, kept in the log."
    )


class SlotTicketCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    template: int = Field(description="A slot template id from GET /api/v1/slot-templates: 101 Briefing, 102 Note.")
    recipient: Recipient
    slots: dict[str, Any] = Field(default_factory=dict, description="The slots, see the template's schema.")
    tone: Literal[TONES] | None = None  # type: ignore[valid-type]
    kind: Literal[KINDS] | None = None  # type: ignore[valid-type]
    from_user: Recipient | None = None
    to_user: Recipient | None = None
    sender: str | None = Field(default=None, max_length=40)
    send_at: datetime | None = None
    delivery: Literal["now", "at", "on_release"] | None = Field(
        default=None, description="As for /tickets: now, at, or on_release (the recipient's pile)."
    )
    hold: bool = Field(default=False, description="Keep the ticket until released, as for /tickets.")
    hold_key: str | None = Field(default=None, max_length=40, examples=["user-home"])
    idempotency_key: str | None = Field(
        default=None,
        max_length=120,
        description="A second request with the same key returns the first ticket and prints nothing new.",
        examples=["morning:yannic:2026-10-26"],
    )
    blocks: list[Block] = Field(
        default_factory=list,
        max_length=8,
        description="Home Assistant blocks printed after the slots, read at print time, as for /tickets.",
    )


class TicketCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    recipient: Recipient = Field(description="A fixed recipient: yannic or wife.")
    message: str = Field(min_length=1, max_length=2000)
    text_state: Literal["formatted", "unformatted"] = Field(
        default="formatted",
        description=(
            "'formatted' prints the text exactly as sent. 'unformatted' (for example speech-to-text) "
            "is first cleaned up by the text model. If the model is down, the text is sent as it is."
        ),
    )
    title: str | None = Field(default=None, max_length=80, examples=["Dinner"])
    sender: str | None = Field(
        default=None,
        max_length=40,
        description="Who asked for the ticket, for the log. For example home-assistant or hermes.",
        examples=["home-assistant"],
    )
    template: int | Literal["auto"] = Field(
        default="auto",
        description=(
            "A template id from GET /api/v1/templates, which must belong to the recipient's "
            "group, or 'auto' to let the decision model or the rules choose. Chosen when the "
            "request arrives, not when it prints."
        ),
    )
    kind: Literal[KINDS] | None = Field(  # type: ignore[valid-type]
        default=None,
        description="What the ticket is for. Left out, the template's kind is used, or 'note'.",
    )
    tone: Literal[TONES] | None = Field(  # type: ignore[valid-type]
        default=None,
        description="How it sounds. Left out, 'neutral'.",
    )
    from_user: Recipient | None = Field(
        default=None, description="The person who wrote it, when it is a message to the other person."
    )
    to_user: Recipient | None = Field(
        default=None, description="The person it is for. With from_user, it is an inbox item."
    )
    delivery: Literal["now", "at", "on_release"] | None = Field(
        default=None,
        description=(
            "now: print and cut at once. at: print at send_at. on_release: wait in the recipient's "
            "pile and print with their next POST /api/v1/people/{person}/release. Omitted, it is at "
            "when send_at is set, otherwise now."
        ),
    )
    blocks: list[Block] = Field(
        default_factory=list,
        max_length=8,
        description=(
            "Live data from Home Assistant, fetched when the request arrives. 'value' prints a "
            "label and state. 'sparkline' prints a labelled graph of recent history."
        ),
    )
    send_at: datetime | None = Field(
        default=None,
        description=(
            "When to print, as ISO 8601. Values without a timezone use the server's "
            "PRINTARR_TIMEZONE. Omit to print as soon as possible. Cannot be combined with hold."
        ),
        examples=["2026-10-24T17:30:00"],
    )
    hold: bool = Field(
        default=False,
        description="Keep the ticket until POST /tickets/{id}/release or /holds/{hold_key}/release.",
    )
    idempotency_key: str | None = Field(
        default=None,
        max_length=120,
        description=(
            "Makes the request safe to repeat, for example after a timeout. A second request "
            "with the same key returns the first ticket and prints nothing new. "
            "Use one key per logical ticket, such as morning:yannic:2026-10-26."
        ),
        examples=["morning:yannic:2026-10-26"],
    )
    hold_key: str | None = Field(
        default=None,
        max_length=40,
        description="Name for a group of held tickets, for example user-home. Used by /holds/{hold_key}/release.",
        examples=["user-home"],
    )


class ModelSettings(BaseModel):
    enabled: bool
    base_url: str = Field(description="OpenAI-compatible base URL, for example http://192.0.2.231:11434/v1. Empty means rules only.")
    model: str = Field(description="Decision model: picks templates and decorations. For example d1:latest.")
    text_model: str = Field(description="Text model for paragraphs, used later. For example granite4.2:3b.")
    timeout: float = Field(ge=1, le=30)


class ModelSettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    base_url: str | None = Field(default=None, max_length=300)
    model: str | None = Field(default=None, min_length=1, max_length=120)
    text_model: str | None = Field(default=None, min_length=1, max_length=120)
    timeout: float | None = Field(default=None, ge=1, le=30)


class TicketOut(BaseModel):
    id: str
    recipient: str
    sender: str | None
    title: str | None
    message: str
    status: Status
    hold_key: str | None
    send_at: datetime
    next_attempt_at: datetime
    attempts: int
    last_error: str | None
    template_id: int
    text_state: Literal["formatted", "unformatted"]
    decorations: list[str]
    selection: Literal["explicit", "model", "rule"]
    created_at: datetime
    updated_at: datetime
    printed_at: datetime | None
    kind: str
    tone: str
    from_user: str | None = None
    to_user: str | None = None
    inbox_state: str | None = None
    choice_source: str | None = None
    render_ms: int | None = None
    print_ms: int | None = None
    delivery: str = "now"
    strip_id: str | None = None
    strip_trigger: str | None = None
    moods: str = ""


class ChoiceOut(BaseModel):
    template_id: int
    decorations: list[str]
    selection: Literal["explicit", "model", "rule"]


class PreviewOut(ChoiceOut):
    text: str = Field(description="The receipt as it would be printed, as plain text.")
    width: int
    warnings: list[str] = Field(default_factory=list, description="Things to check before printing.")


class TemplateOut(BaseModel):
    id: int
    name: str
    recipient: str
    title_align: Literal["left", "center"]
    tall_title: bool
    rule: str
    optional_decorations: list[str]
    default_decorations: list[str]


class AlertSettingsOut(BaseModel):
    telegram_configured: bool
    telegram_token_hint: str = Field(description="Last four characters of the bot token, never the full token.")
    telegram_chat_id: str


class AlertSettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    telegram_token: str | None = Field(default=None, max_length=200)
    telegram_chat_id: str | None = Field(default=None, max_length=50)


class HASettingsOut(BaseModel):
    url: str
    token_configured: bool
    token_hint: str = Field(description="Last four characters of the access token, never the full token.")


class HASettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str | None = Field(default=None, max_length=300, examples=["http://192.168.1.10:8123"])
    token: str | None = Field(default=None, max_length=500)


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


def resolve_delivery(
    delivery: str | None, send_at: datetime | None, hold: bool
) -> tuple[bool, str]:
    """Return (held, delivery). Omitted, a ticket is 'at' when it has send_at, otherwise 'now'.

    'on_release' tickets wait in the person's pile until POST /people/{person}/release.
    """
    if delivery is None:
        return hold, "at" if send_at is not None else "now"
    if delivery == "on_release":
        if send_at is not None:
            raise HTTPException(status_code=422, detail="delivery on_release cannot take send_at")
        return True, "on_release"
    if delivery == "at":
        if send_at is None:
            raise HTTPException(status_code=422, detail="delivery at needs send_at")
        if hold:
            raise HTTPException(status_code=422, detail="delivery at cannot be held")
        return False, "at"
    if send_at is not None:
        raise HTTPException(status_code=422, detail="delivery now cannot take send_at; use delivery at")
    return hold, "now"


def _choice_out(choice: Choice) -> ChoiceOut:
    return ChoiceOut(
        template_id=choice.template.id,
        decorations=list(choice.decorations),
        selection=choice.selection,
    )


MAX_IMPORT_BYTES = 200 * 1024 * 1024  # a database larger than this is refused
PAPER_WARN_LINES = 20  # a receipt longer than this uses a lot of paper; warn, do not block


def preview_warnings(text: str) -> list[str]:
    """Checks for a rendered receipt: length, and characters that print as "?"."""
    warnings: list[str] = []
    rows = text.splitlines()
    if len(rows) > PAPER_WARN_LINES:
        warnings.append(
            f"This ticket is {len(rows)} lines long. Receipts over {PAPER_WARN_LINES} lines "
            "use a lot of paper, so check it is what you meant."
        )
    question = sorted({ch for row in rows for ch in printed_as_question(row)})
    if question:
        warnings.append("These characters will print as '?': " + " ".join(question))
    return warnings


def create_app(settings: Settings | None = None, transport: Transport | None = None) -> FastAPI:
    settings = settings or load_settings()
    transport = transport or build_transport(settings)
    store = TicketStore(settings.db_path)
    width = settings.paper_width
    runtime = {"scheduler": False}

    def read_alert_settings() -> AlertSettings:
        return AlertSettings(
            telegram_token=store.get_setting("alert_telegram_token") or "",
            telegram_chat_id=store.get_setting("alert_telegram_chat_id") or "",
        )

    notifier = Notifier(read_alert_settings)
    metrics = Metrics()
    scheduler = Scheduler(store, transport, settings, notifier=notifier, metrics=metrics)
    nightly = NightlyBackup(
        settings.db_path, store.backup_dir, settings.tzinfo, settings.backup_hour, settings.backup_keep
    )

    def read_model_settings() -> ModelSettings:
        """Stored settings win. Environment values only seed the first start."""
        return ModelSettings(
            enabled=(store.get_setting("llm_enabled") or "").lower() == "true",
            base_url=store.get_setting("llm_base_url") or "",
            model=store.get_setting("llm_model") or settings.llm_model,
            text_model=store.get_setting("llm_text_model") or settings.llm_text_model,
            timeout=float(store.get_setting("llm_timeout") or settings.llm_timeout),
        )

    def current_model() -> SystemOneModel | None:
        current = read_model_settings()
        if not (current.enabled and current.base_url):
            return None
        return SystemOneModel(current.base_url, current.model, current.timeout)

    def seed_model_settings() -> None:
        defaults = {
            "llm_enabled": "true" if settings.llm_enabled else "false",
            "llm_base_url": settings.llm_base_url,
            "llm_model": settings.llm_model,
            "llm_text_model": settings.llm_text_model,
            "llm_timeout": str(settings.llm_timeout),
        }
        for key, value in defaults.items():
            if store.get_setting(key) is None:
                store.set_setting(key, value)

    def health_snapshot() -> tuple[dict[str, Any], bool]:
        checks: dict[str, str] = {}
        try:
            store.get_setting("llm_enabled")
            checks["database"] = "ok"
        except Exception as exc:
            checks["database"] = f"error: {exc}"
        try:
            transport.check()
            checks["printer"] = "ok"
        except PrinterError as exc:
            checks["printer"] = f"unreachable: {exc}"
        current = read_model_settings()
        if not (current.enabled and current.base_url):
            checks["decision_model"] = "not in use"
        else:
            checks["decision_model"] = "down" if notifier.is_active("model") else "ok"
        checks["scheduler"] = "running" if runtime["scheduler"] else "disabled"
        for key in FAULT_TEXT:
            checks[key] = "fault" if notifier.is_active(key) else "ok"
        checks["paper_near_end"] = "warning" if runtime.get("paper_near_end") else "ok"
        up = checks["database"] == "ok" and checks["printer"] == "ok"
        return {"status": "ok" if up else "down", "checks": checks}, up

    def watch_printer() -> None:
        """Every minute: reachability, then the printer's own status (paper, cover, cutter)."""
        metrics.incr("status_polls")
        try:
            answers = transport.read_status()
        except PrinterError as exc:
            notifier.problem("printer", f"printer unreachable: {exc}")
            return
        notifier.recovered("printer", "printer is reachable again")
        status = decode(answers)
        for key in status.known & set(FAULT_TEXT):
            if key in status.faults:
                notifier.problem(key, FAULT_TEXT[key])
            else:
                notifier.recovered(key, f"{FAULT_TEXT[key]} cleared")
        if "paper_near_end" in status.known:
            runtime["paper_near_end"] = "paper_near_end" in status.warnings  # shown in health, not alerted

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        store.init()
        seed_model_settings()
        interrupted = store.fail_interrupted()
        if interrupted:
            logger.warning("%d ticket(s) were printing at restart and were not reprinted: %s",
                           len(interrupted), ", ".join(interrupted))
            notifier.send_now(
                f"Printarr: {len(interrupted)} ticket(s) were interrupted by a restart and were not "
                "reprinted, to avoid a duplicate. Check the paper, then retry them from the web UI if needed."
            )
        worker = (
            SchedulerThread(scheduler, settings.poll_interval)
            if settings.scheduler_enabled
            else None
        )
        if worker:
            worker.start()
        runtime["scheduler"] = worker is not None
        heartbeat = HeartbeatThread(watch_printer)
        heartbeat.start()
        backups = NightlyThread(nightly) if settings.backup_enabled else None
        if backups:
            backups.start()
        try:
            yield
        finally:
            heartbeat.stop()
            if backups:
                backups.stop()
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

    def current_text_model() -> OpenAICompatibleModel | None:
        current = read_model_settings()
        if not (current.enabled and current.base_url):
            return None
        return OpenAICompatibleModel(current.base_url, current.text_model, current.timeout)

    def prepare_text(body: TicketCreate) -> str:
        """Clean up unformatted text before rendering. Falls back to the text as sent."""
        if body.text_state == "formatted":
            return body.message
        model = current_text_model()
        if model is None:
            return body.message
        try:
            cleaned = model.rewrite(body.message)
        except Exception as exc:
            logger.warning("text model unusable, sending text as sent: %s", exc)
            notifier.problem("text_model", f"text model down, sent text uncleaned: {exc}")
            return body.message
        notifier.recovered("text_model", "text model answers again")
        return cleaned

    def on_model_result(error: Exception | None) -> None:
        if error is None:
            notifier.recovered("model", "decision model answers again")
        else:
            notifier.problem("model", f"decision model down, using rules: {error}")

    def choose(body: TicketCreate) -> Choice:
        template_id = None if body.template == "auto" else body.template
        try:
            return resolve_choice(
                body.recipient,
                body.title,
                body.message,
                template_id,
                current_model(),
                on_model_result,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None

    def home_assistant() -> HAClient | None:
        url = store.get_setting("ha_url") or ""
        token = store.get_setting("ha_token") or ""
        return HAClient(url, token) if url and token else None

    def prepare_blocks(body: TicketCreate) -> list[Line]:
        """Fetch Home Assistant data now. An unreachable Home Assistant rejects the request."""
        if not body.blocks:
            return []
        try:
            return resolve_blocks(body.blocks, home_assistant())
        except HAError as exc:
            logger.warning("home assistant data unavailable: %s", exc)
            raise HTTPException(status_code=502, detail=f"ticket not queued: {exc}") from None

    def render_preview(body: TicketCreate, choice: Choice, message: str, extra: list[Line]) -> str:
        receipt = Receipt(
            recipient=RECIPIENTS[body.recipient],
            sender=body.sender,
            title=body.title,
            message=message,
            sent_at=datetime.fromtimestamp(_resolve_send_at(body.send_at, settings.tzinfo) / 1000, tz=settings.tzinfo),
        )
        if choice.template.design:
            return to_text([design_line(choice.template.design, message, home_assistant())[0]], width)
        lines = render_lines(receipt, width, choice.template, choice.decorations, extra)
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
            if t.group != "slots"
        ]

    @api.get("/slot-templates", tags=["templates"])
    def list_slot_templates() -> list[dict[str, Any]]:
        """Slot templates: fill their slots and POST them to /api/v1/tickets/slots."""
        return [
            {"id": template_id, "name": slot_name, "schema": f"/api/v1/templates/{template_id}/schema"}
            for template_id, slot_name in SLOT_NAMES.items()
        ]

    @api.get("/templates/{template_id}/schema", tags=["templates"])
    def slot_template_schema(template_id: int) -> dict[str, Any]:
        """The slots of a slot template as JSON Schema: names, types, limits and descriptions."""
        if not is_slot_template(template_id):
            raise HTTPException(status_code=404, detail=f"template {template_id} has no slots; see GET /api/v1/slot-templates")
        return slot_schema(template_id)

    @api.post("/tickets/slots", status_code=201, response_model=TicketOut, tags=["tickets"])
    def create_slot_ticket(body: SlotTicketCreate) -> dict[str, Any]:
        """Queue a slot ticket. Slots are checked first; a bad slot returns 422 with each problem."""
        held, delivery = resolve_delivery(body.delivery, body.send_at, body.hold)
        if body.hold and body.send_at is not None:
            raise HTTPException(status_code=422, detail="hold and send_at cannot be combined")
        if body.hold_key and not body.hold:
            raise HTTPException(status_code=422, detail="hold_key needs hold: true")
        if body.idempotency_key:
            existing = store.get_by_key(body.idempotency_key)
            if existing is not None:
                return existing
        if not is_slot_template(body.template):
            raise HTTPException(status_code=422, detail=f"template {body.template} is not a slot template")
        try:
            checked = validate_slots(body.template, body.slots)
        except SlotProblems as exc:
            raise HTTPException(status_code=422, detail=exc.problems) from None
        now = datetime.now(settings.tzinfo)
        filled = autofill(body.template, checked.model_dump(exclude_none=True), body.recipient, now)
        if body.blocks and home_assistant() is None:
            raise HTTPException(status_code=422, detail="Home Assistant is not configured; set its URL and token first")
        try:
            block_lines = resolve_blocks(body.blocks, home_assistant()) if body.blocks else []
        except HAError as exc:
            raise HTTPException(status_code=502, detail=f"ticket not queued: {exc}") from None
        render_started = time.perf_counter()
        try:  # check the layout now, so a queued ticket always prints
            encode(
                slot_lines(filled) + block_lines,
                feed=template_by_id(body.template).feed,
                raster_mode=settings.raster_mode,
            )
        except Exception as exc:
            logger.exception("slot rendering failed; ticket not queued")
            raise HTTPException(status_code=500, detail=f"rendering failed, ticket not queued: {exc}") from None
        render_ms = round((time.perf_counter() - render_started) * 1000)
        kind = body.kind or ("morning" if body.template == BRIEFING else "note")
        summary = str(filled.get("paragraph") or filled.get("title") or filled.get("greeting") or "")
        return store.create(
            kind=kind,
            tone=body.tone or DEFAULT_TONE,
            from_user=body.from_user,
            to_user=body.to_user,
            recipient=body.recipient,
            message=summary or "(slots)",
            sender=body.sender,
            title=filled.get("title"),
            send_at_ms=_resolve_send_at(body.send_at, settings.tzinfo),
            template_id=body.template,
            decorations=(),
            selection="explicit",
            choice_source="explicit",
            render_ms=render_ms,
            slots_json=json.dumps(filled, default=str),
            held=held,
            delivery=delivery,
            hold_key=body.hold_key,
            idempotency_key=body.idempotency_key,
            blocks_json=json.dumps([block.model_dump() for block in body.blocks]),
        )

    @api.post("/tickets", status_code=201, response_model=TicketOut, tags=["tickets"])
    def create_ticket(body: TicketCreate) -> dict[str, Any]:
        """Queue a ticket. The template is chosen now, so printing needs no more work."""
        held, delivery = resolve_delivery(body.delivery, body.send_at, body.hold)
        if body.hold and body.send_at is not None:
            raise HTTPException(status_code=422, detail="hold and send_at cannot be combined")
        if body.hold_key and not body.hold:
            raise HTTPException(status_code=422, detail="hold_key needs hold: true")
        if body.idempotency_key:
            existing = store.get_by_key(body.idempotency_key)
            if existing is not None:
                return existing
        choice = choose(body)
        message = prepare_text(body)
        if body.blocks and home_assistant() is None:
            raise HTTPException(status_code=422, detail="Home Assistant is not configured; set its URL and token first")
        render_started = time.perf_counter()
        try:  # reject now rather than queue a ticket that cannot print
            receipt = Receipt(
                recipient=RECIPIENTS[body.recipient],
                sender=body.sender,
                title=body.title,
                message=message,
                sent_at=datetime.now(settings.tzinfo),
            )
            if choice.template.design:
                lines = [placeholder_line(choice.template.design, message)]
            else:
                lines = render_lines(receipt, width, choice.template, choice.decorations)
            encode(lines, feed=choice.template.feed, raster_mode=settings.raster_mode)
        except Exception as exc:
            logger.exception("rendering failed; ticket not queued")
            raise HTTPException(status_code=500, detail=f"rendering failed, ticket not queued: {exc}") from None
        render_ms = round((time.perf_counter() - render_started) * 1000)
        kind = body.kind or (choice.template.kind if choice.template.kind in KINDS else DEFAULT_KIND)
        return store.create(
            kind=kind,
            tone=body.tone or DEFAULT_TONE,
            from_user=body.from_user,
            to_user=body.to_user,
            render_ms=render_ms,
            recipient=body.recipient,
            message=message,
            text_state=body.text_state,
            blocks_json=json.dumps([block.model_dump() for block in body.blocks]),
            sender=body.sender,
            title=body.title,
            send_at_ms=_resolve_send_at(body.send_at, settings.tzinfo),
            template_id=choice.template.id,
            decorations=choice.decorations,
            selection=choice.selection,
            held=held,
            delivery=delivery,
            hold_key=body.hold_key,
            idempotency_key=body.idempotency_key,
        )

    @api.post("/tickets/{ticket_id}/release", response_model=TicketOut, tags=["tickets"])
    def release_ticket(ticket_id: str) -> dict[str, Any]:
        """Release a held ticket. It prints within seconds, since its template is already chosen."""
        return guarded(store.release, ticket_id)

    @api.get("/blocks", tags=["templates"])
    def list_blocks() -> list[dict[str, Any]]:
        """The block catalogue: each type, what it is for, its moods and where its slot schema is."""
        return compose_catalogue()

    @api.get("/blocks/{name}/schema", tags=["templates"])
    def block_schema_route(name: str) -> dict[str, Any]:
        """The slots of one block type as JSON Schema."""
        if name not in compose_blocks:
            raise HTTPException(status_code=404, detail=f"unknown block type {name!r}; see GET /api/v1/blocks")
        return compose_block_schema(name)

    @api.post("/tickets/compose", status_code=201, response_model=TicketOut, tags=["tickets"])
    def create_composed_ticket(body: ComposeCreate) -> dict[str, Any]:
        """Queue a composed ticket: blocks stacked in order on one card shell. Blocks are checked first."""
        held, delivery = resolve_delivery(body.delivery, body.send_at, body.hold)
        if body.hold_key and not held:
            raise HTTPException(status_code=422, detail="hold_key needs hold: true")
        if body.idempotency_key:
            existing = store.get_by_key(body.idempotency_key)
            if existing is not None:
                return existing
        try:
            checked = compose_validate(body.blocks)
        except BlockProblem as exc:
            raise HTTPException(status_code=422, detail=exc.problems) from None
        render_started = time.perf_counter()
        try:  # check the layout now, so a queued ticket always prints
            encode(compose_lines(checked), feed=template_by_id(103).feed, raster_mode=settings.raster_mode)
        except Exception as exc:
            logger.exception("composed rendering failed; ticket not queued")
            raise HTTPException(status_code=500, detail=f"rendering failed, ticket not queued: {exc}") from None
        render_ms = round((time.perf_counter() - render_started) * 1000)
        first = checked[0]["slots"]
        summary = str(first.get("text") or first.get("label") or "(composed)")
        return store.create(
            kind=body.kind or "note",
            tone=body.tone or DEFAULT_TONE,
            from_user=body.from_user,
            to_user=body.to_user,
            recipient=body.recipient,
            message=summary,
            sender=body.sender,
            title=None,
            send_at_ms=_resolve_send_at(body.send_at, settings.tzinfo),
            template_id=103,
            decorations=(),
            selection="explicit",
            choice_source="explicit",
            render_ms=render_ms,
            slots_json=json.dumps({"blocks": checked}, default=str),
            held=held,
            delivery=delivery,
            hold_key=body.hold_key,
            idempotency_key=body.idempotency_key,
            moods=",".join(block["mood"] for block in checked),
        )

    @api.post("/people/{person}/release", tags=["tickets"])
    def release_person(person: Recipient, body: PersonRelease) -> dict[str, Any]:
        """Print this person's pile as strips, cutting after each. Only this person's tickets go on a strip."""
        try:
            strips = scheduler.print_release(person, body.trigger)
        except PrinterError as exc:
            raise HTTPException(status_code=502, detail=f"printer unreachable, pile kept: {exc}") from None
        return {"person": person, "trigger": body.trigger, "strips": strips}

    @api.post("/holds/{hold_key}/release", response_model=list[TicketOut], tags=["tickets"])
    def release_hold(hold_key: str) -> list[dict[str, Any]]:
        """Release every held ticket with this key. Home Assistant can call this on arrival."""
        return store.release_hold(hold_key)

    insight_cache = InsightCache()

    @api.get("/insights/entities", tags=["insights"])
    def insight_entities(
        person: Recipient = Query(description="yannic or wife."),
        limit: int = Query(12, ge=1, le=30),
    ) -> list[dict[str, Any]]:
        """Numeric Home Assistant entities for a briefing, most notable first.

        Each item has the current value, 30-day mean and spread, a z-score, a 7-day trend and
        a plain reason. Hermes picks the graph slots from this list. Cached for five minutes.
        """
        client = home_assistant()
        if client is None:
            raise HTTPException(status_code=422, detail="Home Assistant is not configured")

        found = insight_cache.get(person, limit, lambda: collect(person, client.numeric_history, limit))
        return [asdict(item) for item in found]

    @api.get("/settings/model", response_model=ModelSettings, tags=["settings"])
    def get_model_settings() -> ModelSettings:
        return read_model_settings()

    @api.put("/settings/model", response_model=ModelSettings, tags=["settings"])
    def update_model_settings(patch: ModelSettingsPatch) -> ModelSettings:
        """Change the decision model. Saved in the database, so it survives restarts."""
        for field, key in SETTING_KEYS.items():
            value = getattr(patch, field)
            if value is not None:
                store.set_setting(key, str(value).lower() if isinstance(value, bool) else str(value))
        return read_model_settings()

    @api.get("/health", tags=["monitoring"], responses={503: {"description": "Printer or database down"}})
    def health() -> Response:
        """For Uptime Kuma. Returns 503 when the printer or database is down."""
        snapshot, up = health_snapshot()
        return Response(
            content=json.dumps(snapshot),
            media_type="application/json",
            status_code=200 if up else 503,
        )

    @api.get("/backup/export", tags=["backup"], response_class=Response)
    def export_backup() -> Response:
        """Download a consistent copy of the whole database (tickets and settings) as an .db file."""
        data = store.export_bytes()
        name = f"printarr-{datetime.now(settings.tzinfo):%Y%m%d-%H%M%S}.db"
        return Response(
            content=data,
            media_type="application/vnd.sqlite3",
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )

    @api.post("/backup/import", tags=["backup"], responses={422: {"description": "Not a printarr database"}})
    async def import_backup(
        request: Request,
        confirm: str = Query("", description="Must be 'replace'"),
    ) -> dict[str, Any]:
        """Replace the database with a file from /backup/export. Send the raw file as the body.

        The current database is kept first as backups/pre-import-*.db. Any schema upgrade runs
        after the copy. Use confirm=replace so a stray request cannot wipe the data by accident.
        """
        if confirm != "replace":
            raise HTTPException(status_code=400, detail="add ?confirm=replace to replace the database")
        data = await request.body()
        if len(data) > MAX_IMPORT_BYTES:
            raise HTTPException(status_code=413, detail="file is larger than 200 MB")
        try:
            return await run_in_threadpool(
                import_bytes, data, settings.db_path, store.backup_dir, datetime.now(settings.tzinfo)
            )
        except BackupError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None

    @api.get("/settings/alerts", response_model=AlertSettingsOut, tags=["settings"])
    def get_alert_settings() -> AlertSettingsOut:
        current = read_alert_settings()
        token = current.telegram_token
        return AlertSettingsOut(
            telegram_configured=bool(token and current.telegram_chat_id),
            telegram_token_hint=f"...{token[-4:]}" if token else "",
            telegram_chat_id=current.telegram_chat_id,
        )

    @api.put("/settings/alerts", response_model=AlertSettingsOut, tags=["settings"])
    def update_alert_settings(patch: AlertSettingsPatch) -> AlertSettingsOut:
        """Set the Telegram bot token and chat ID. Send an empty string to clear a value."""
        keys = {
            "telegram_token": "alert_telegram_token",
            "telegram_chat_id": "alert_telegram_chat_id",
        }
        for field, key in keys.items():
            value = getattr(patch, field)
            if value is not None:
                store.set_setting(key, value)
        return get_alert_settings()

    @api.post("/alerts/test", tags=["settings"])
    def test_alert() -> dict[str, bool]:
        current = read_alert_settings()
        if not (current.telegram_token and current.telegram_chat_id):
            raise HTTPException(status_code=400, detail="Telegram is not configured")
        try:
            send_telegram(current.telegram_token, current.telegram_chat_id, "Printarr test alert: all good.")
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Telegram send failed: {exc}") from None
        return {"sent": True}

    @api.get("/settings/ha", response_model=HASettingsOut, tags=["settings"])
    def get_ha_settings() -> HASettingsOut:
        token = store.get_setting("ha_token") or ""
        return HASettingsOut(
            url=store.get_setting("ha_url") or "",
            token_configured=bool(token),
            token_hint=f"...{token[-4:]}" if token else "",
        )

    @api.put("/settings/ha", response_model=HASettingsOut, tags=["settings"])
    def update_ha_settings(patch: HASettingsPatch) -> HASettingsOut:
        """Home Assistant base URL and long-lived access token. Empty string clears a value."""
        if patch.url is not None:
            store.set_setting("ha_url", patch.url)
        if patch.token is not None:
            store.set_setting("ha_token", patch.token)
        return get_ha_settings()

    @api.post("/settings/ha/test", tags=["settings"])
    def test_ha() -> dict[str, bool]:
        client = home_assistant()
        if client is None:
            raise HTTPException(status_code=400, detail="Home Assistant URL and token are not set")
        try:
            client.ping()
        except HAError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from None
        return {"reachable": True}

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def web_ui() -> str:
        return WEB_UI

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
        message = prepare_text(body)
        extra = prepare_blocks(body)
        text = render_preview(body, choice, message, extra)
        return {
            **_choice_out(choice).model_dump(),
            "text_state": body.text_state,
            "text": text,
            "width": width,
            "warnings": preview_warnings(text),
        }

    def log_filters(recipient: str | None, since_hours: int | None) -> dict[str, Any]:
        since_ms = None if since_hours is None else now_ms() - since_hours * 3_600_000
        return {"recipient": recipient, "since_ms": since_ms}

    @api.get("/log", response_model=list[TicketOut], tags=["log"])
    def log_list(
        recipient: Recipient | None = None,
        kind: str | None = None,
        tone: str | None = None,
        template_id: int | None = None,
        status: Status | None = None,
        since_hours: int | None = Query(None, ge=1),
        limit: int = Query(200, ge=1, le=1000),
        offset: int = Query(0, ge=0),
    ) -> list[dict[str, Any]]:
        """Every ticket, oldest first, with the kind, tone, template, choice source and timings."""
        return store.log(
            kind=kind, tone=tone, template_id=template_id, status=status,
            limit=limit, offset=offset, **log_filters(recipient, since_hours),
        )

    @api.get("/log/summary", tags=["log"])
    def log_summary(
        recipient: Recipient | None = None,
        since_hours: int | None = Query(None, ge=1),
    ) -> dict[str, dict[str, int]]:
        """Counts by kind, tone, template, status and choice source, to see what is used."""
        filters = log_filters(recipient, since_hours)
        return {
            "by_kind": store.log_counts("kind", **filters),
            "by_tone": store.log_counts("tone", **filters),
            "by_template": store.log_counts("template_id", **filters),
            "by_status": store.log_counts("status", **filters),
            "by_choice": store.log_counts("choice_source", **filters),
        }

    @api.get("/log/export", tags=["log"], responses={200: {"content": {"text/csv": {}}}})
    def log_export(
        format: Literal["csv", "json"] = "csv",
        recipient: Recipient | None = None,
        since_hours: int | None = Query(None, ge=1),
    ) -> Response:
        """Every ticket in the log as CSV or JSON, for tuning the templates from real use."""
        rows = store.log(limit=1000000, **log_filters(recipient, since_hours))
        if format == "json":
            return Response(json.dumps(rows, default=str), media_type="application/json")
        columns = [
            "id", "created_at", "recipient", "from_user", "to_user", "kind", "tone", "template_id",
            "choice_source", "selection", "decorations", "status", "inbox_state", "render_ms",
            "print_ms", "printed_at", "title", "sender", "message", "moods", "strip_id", "strip_trigger",
        ]
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({**row, "decorations": ",".join(row["decorations"])})
        return Response(buffer.getvalue(), media_type="text/csv")

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
        live = scheduler.live_lines(ticket)
        return to_text(render_ticket_lines(ticket, settings.tzinfo, width, live), width)

    @api.get(
        "/tickets/{ticket_id}/escpos",
        response_class=Response,
        tags=["tickets"],
        responses={200: {"content": {"application/octet-stream": {}}}},
    )
    def ticket_escpos(ticket_id: str) -> Response:
        """The exact ESC/POS byte stream for this ticket. The simulator reads this."""
        ticket = ticket_or_404(ticket_id)
        data = encode(
            render_ticket_lines(ticket, settings.tzinfo, width, scheduler.live_lines(ticket)),
            feed=ticket_feed(ticket),
            raster_mode=settings.raster_mode,
        )
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
            transport.send(encode(render_lines(receipt, width), raster_mode=settings.raster_mode))
        except PrinterError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from None
        return PrinterStatus(mode=settings.printer_mode, target=transport.target, reachable=True)

    @api.get("/printer/self-check", tags=["printer"])
    def printer_self_check() -> dict[str, Any]:
        """Check the link and read the printer's status bytes. Prints nothing.

        `faults` are the blocking keys the queue pauses for. `unanswered` lists keys whose
        status request got no reply, so they could not be checked.
        """
        base: dict[str, Any] = {"mode": settings.printer_mode, "target": transport.target}
        try:
            transport.check()
            answers = transport.read_status()
        except PrinterError as exc:
            return {**base, "reachable": False, "error": str(exc)}
        status = decode(answers)
        return {
            **base,
            "reachable": True,
            "faults": sorted(status.faults),
            "warnings": sorted(status.warnings),
            "unanswered": sorted(set(REQUESTS_FOR_KEY) - status.known),
            "queue_paused": scheduler.paused_reason,
        }

    @api.get("/metrics", tags=["monitoring"])
    def get_metrics() -> dict[str, Any]:
        """Counters since start: tickets printed, failures, dead letters, interrupted jobs, pauses."""
        return {**metrics.snapshot(), "queue_paused": scheduler.paused_reason}

    app.include_router(api)
    app.state.watch_printer = watch_printer  # tests and the heartbeat share this check
    return app


app = create_app()
