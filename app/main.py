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

import threading

from fastapi import APIRouter, FastAPI, Header, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from starlette.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from app import ticket_images
from app.notify import MAX_TEXT, NotifyLimiter, clean_text
from app.web import WEB_UI
from app.version import PACKAGE_VERSION, build_info

from app.alerts import AlertSettings, HeartbeatThread, Notifier, send_telegram
from app.backup import BackupError, NightlyBackup, NightlyThread, import_bytes
from app.config import Settings, load_settings
from app.insights import InsightCache, collect
from app.escpos import encode, to_text
from app.kinds import DEFAULT_KIND, DEFAULT_TONE, KINDS, TONES
from app.printer import PrinterError, SwitchableTransport, Transport, build_transport
from app import discovery
from app import setup as setup_flow
from app.discovery import DiscoverRequest
from app.setup import CheckName, SetupValues, check_item, run_checks
from app.setup_page import SETUP_UI
from app.metrics import Metrics
from app.status import FAULT_TEXT, REQUESTS_FOR_KEY, decode
from app.receipt import Line, Receipt, line_to_dict, render_ticket_lines, ticket_feed
from app.render.registry import design_line, placeholder_line
from app.blocks import Block, resolve_blocks
from app.ha import HAClient, HAError
from app.scheduler import ReleaseIncomplete, Scheduler, SchedulerThread
from app.store import TicketNotFound, TicketStateError, TicketStore, now_ms
from app.text import printed_as_question
from app.compose import (
    note_card_lines,
    ticket_lines,
    plain_message,
    BLOCKS as compose_blocks,
    BlockProblem,
    catalogue as compose_catalogue,
    block_schema as compose_block_schema,
    compose_render,
    summary as compose_summary,
    validate_blocks as compose_validate,
)
from app.slots import (
    BRIEFING,
    SLOT_NAMES,
    SlotProblems,
    autofill,
    is_slot_template,
)
from app.slots import schema as slot_schema
from app.slots import validate as validate_slots
from app.templates import (
    RECIPIENTS,
    Deadline,
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


class NotifyIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    text: str = Field(min_length=1, max_length=MAX_TEXT, description="The message. Plain text, up to 1000 characters.")


class ApiProblem(Exception):
    """A 4xx that tells the caller, and an agent reading the reply, how to fix the request.

    The reply is {detail, hint, example}: detail says what is wrong, hint says what to do, and example
    shows a request that works.
    """

    def __init__(self, status_code: int, detail: Any, hint: str, example: Any = None) -> None:
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail
        self.hint = hint
        self.example = example


VALIDATION_HINT = (
    "Each field named in detail is wrong or missing. loc gives its path in the body. Valid types, "
    "moods and templates: GET /api/v1/blocks, GET /api/v1/slot-templates, GET /api/v1/templates. "
    "Every field and its allowed values: /openapi.json, or /docs."
)
HA_HINT = (
    "Home Assistant is not set up. Save its URL and a long-lived token in settings: "
    "PUT /api/v1/settings/ha, or use the setup wizard. Then retry."
)
COMPOSE_EXAMPLE = {
    "recipient": "yannic",
    "blocks": [
        {"type": "greeting", "mood": "happy", "slots": {"greeting": "GOOD MORNING", "summary": "Two dogs walked."}},
        {"type": "metric", "mood": "factual", "slots": {"label": "Body battery", "value": 72, "unit": "%"}},
    ],
}
BLOCKS_HINT = (
    "Each block is {type, mood, span, slots}. type: one of GET /api/v1/blocks. mood: one of the moods "
    "listed there, or 'auto'. span: 1 to 3 columns, default from the type. slots: check the type's fields "
    "with GET /api/v1/blocks/{type}/schema. problems names each wrong slot as blocks[i].slots.field."
)
SLOT_HINT = (
    "Slot tickets use template 101 (briefing) or 102 (note). See GET /api/v1/slot-templates, then "
    "GET /api/v1/templates/{id}/schema for its slots. problems names each wrong slot."
)
HOLD_HINT = (
    "A held ticket waits for a release. Use hold: true alone to hold until released, or send_at alone to "
    "print at that time, or delivery on_release to wait for a person's release. The two cannot be mixed."
)

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
            "the timezone set in the setup wizard. Omit to print as soon as possible. Cannot be combined with hold."
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
    base_url: str = Field(description="OpenAI-compatible base URL, for example http://192.168.1.231:11434/v1. Empty means rules only.")
    model: str = Field(description="Decision model: picks templates and decorations. For example d1:latest.")
    text_model: str = Field(description="Text model for paragraphs, used later. For example granite4.2:3b.")
    timeout: float = Field(ge=1, le=60)


class ModelSettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    base_url: str | None = Field(default=None, max_length=300)
    model: str | None = Field(default=None, min_length=1, max_length=120)
    text_model: str | None = Field(default=None, min_length=1, max_length=120)
    timeout: float | None = Field(default=None, ge=1, le=60)


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
    notes: list[str] = Field(default_factory=list, description="What was shortened to fit, for composed tickets.")


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
            raise ApiProblem(422, "delivery on_release cannot take send_at",
                             "on_release tickets wait for the person's release. Remove send_at, or use delivery at.",
                             {"delivery": "on_release"})
        return True, "on_release"
    if delivery == "at":
        if send_at is None:
            raise ApiProblem(422, "delivery at needs send_at",
                             "delivery at prints at send_at. Give send_at as local ISO 8601, for example 2026-10-30T10:00:00.",
                             {"delivery": "at", "send_at": "2026-10-30T10:00:00"})
        if hold:
            raise ApiProblem(422, "delivery at cannot be held",
                             "A scheduled ticket prints at its time and is not held. Drop hold, or drop send_at and use hold.",
                             {"delivery": "at", "send_at": "2026-10-30T10:00:00"})
        return False, "at"
    if send_at is not None:
        raise ApiProblem(422, "delivery now cannot take send_at",
                         "delivery now prints straight away. For a later time use delivery at with send_at.",
                         {"delivery": "at", "send_at": "2026-10-30T10:00:00"})
    return hold, "now"


def _choice_out(choice: Choice) -> ChoiceOut:
    return ChoiceOut(
        template_id=choice.template.id,
        decorations=list(choice.decorations),
        selection=choice.selection,
    )


MAX_IMPORT_BYTES = 200 * 1024 * 1024  # a database larger than this is refused
SINCE_HOURS_MAX = 24 * 365 * 10  # ten years; larger values overflow the SQLite integer range
PAPER_WARN_LINES = 20  # a receipt longer than this uses a lot of paper; warn, do not block


CSV_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _csv_safe(value: Any) -> Any:
    """Stop a spreadsheet reading a message as a formula: a leading = + - @ is shown as text."""
    if isinstance(value, str) and value.startswith(CSV_FORMULA_START):
        return "'" + value
    return value


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


# Paths that answer while setup is open: the wizard page, health, the setup routes and the docs.
SETUP_OPEN_PATHS = ("/", "/setup", "/healthz", "/api/v1/health", "/docs", "/openapi.json", "/redoc")


def create_app(settings: Settings | None = None, transport: Transport | None = None) -> FastAPI:
    settings = settings or setup_flow.stored_overrides(load_settings())
    transport = SwitchableTransport(transport or build_transport(settings))
    store = TicketStore(settings.db_path)
    width = settings.paper_width
    runtime = {"scheduler": False, "setup_open": settings.setup_required}
    setup_lock = threading.Lock()

    def read_alert_settings() -> AlertSettings:
        return AlertSettings(
            telegram_token=store.get_setting("alert_telegram_token") or "",
            telegram_chat_id=store.get_setting("alert_telegram_chat_id") or "",
        )

    notifier = Notifier(read_alert_settings)
    metrics = Metrics()
    def printer_waiting() -> bool:
        """True until setup is finished and a printer address is saved. Polling and alerts wait for that."""
        if runtime["setup_open"]:
            return True
        return settings.printer_mode == "tcp" and not (store.get_setting("printer_host") or settings.printer_host)

    scheduler = Scheduler(
        store, transport, settings, notifier=notifier, metrics=metrics, printer_waiting=printer_waiting
    )
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
        if printer_waiting():
            return  # not set up yet: no alert and no poll
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

    def start_setup() -> None:
        """Print a new setup code at every start. Legacy installs already have settings, so they skip the wizard.

        The same code opens the wizard while setup is open, and later opens /setup to change settings.
        """
        if not settings.setup_required:
            return
        if store.get_setting(setup_flow.COMPLETE_KEY) is None and setup_flow.is_legacy_install(store):
            store.set_setting(setup_flow.COMPLETE_KEY, "true")
        runtime["setup_open"] = store.get_setting(setup_flow.COMPLETE_KEY) != "true"
        code = setup_flow.new_code()
        store.set_setting(setup_flow.CODE_HASH_KEY, setup_flow.code_hash(code))
        app.state.setup_code = code
        if runtime["setup_open"]:
            logger.warning(
                "printarr setup: open this printarr's web page in a browser and enter setup code %s. "
                "A new code is printed at each start until setup is finished.",
                code,
            )
        else:
            logger.warning(
                "printarr settings: to change settings, open /setup and enter setup code %s. "
                "A new code is printed at each start.",
                code,
            )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        store.init()
        info = build_info()
        logger.info(
            "printarr version %s, build %s, database schema %s",
            info["version"], info["git_sha"], store.schema_version(),
        )
        setup_flow.make_private(settings.db_path)
        start_setup()
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
        version=PACKAGE_VERSION,
        description=API_DESCRIPTION,
        lifespan=lifespan,
    )
    app.state.scheduler = scheduler

    @app.middleware("http")
    async def setup_gate(request: Request, call_next):
        path = request.url.path
        if runtime["setup_open"] and not (path in SETUP_OPEN_PATHS or path.startswith("/api/v1/setup/")):
            return JSONResponse(
                status_code=503,
                content={
                    "detail": "Setup is not finished. Open the printarr web page and complete the setup wizard.",
                    "setup": "/",
                },
            )
        return await call_next(request)

    api = APIRouter(prefix="/api/v1")

    def require_setup_code(code: str | None) -> None:
        if not setup_flow.code_matches(code, store.get_setting(setup_flow.CODE_HASH_KEY)):
            raise HTTPException(status_code=401, detail="setup code is wrong. Copy it from the printarr log.")

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

    def prepare_text(body: TicketCreate, deadline: Deadline | None = None) -> str:
        """Clean up unformatted text before rendering. Falls back to the text as sent."""
        if body.text_state == "formatted":
            return body.message
        model = current_text_model()
        if model is None:
            return body.message
        try:
            cleaned = model.rewrite(body.message, deadline)
        except Exception as exc:  # the text is printed as sent; a model problem never blocks a print
            notifier.repeated("text_model", f"text model failed, sent text uncleaned: {exc}")
            return body.message
        notifier.recovered("text_model", "text model answers again")
        return cleaned

    def on_model_result(error: Exception | None) -> None:
        if error is None:
            notifier.recovered("model", "decision model answers again")
        else:  # one slow answer is logged; an alert needs repeated failures (see Notifier.repeated)
            notifier.repeated("model", f"decision model failed, using rules: {error}")

    def choose(body: TicketCreate, deadline: Deadline | None = None) -> Choice:
        template_id = None if body.template == "auto" else body.template
        try:
            return resolve_choice(
                body.recipient,
                body.title,
                body.message,
                template_id,
                current_model(),
                on_model_result,
                deadline,
            )
        except ValueError as exc:
            raise ApiProblem(422, str(exc), "template must be 'auto' or a template id from GET /api/v1/templates.") from None

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
        lines = note_card_lines(message, body.sender, body.title) + list(extra)
        return to_text(lines, width)

    @app.get("/healthz", tags=["meta"])
    def healthz() -> dict[str, str]:
        return {"status": "ok", **build_info()}

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
            raise ApiProblem(422, "hold and send_at cannot be combined", HOLD_HINT, {"hold": True})
        if body.hold_key and not body.hold:
            raise ApiProblem(422, "hold_key needs hold: true", HOLD_HINT, {"hold": True, "hold_key": "kitchen-briefing"})
        if body.idempotency_key:
            existing = store.get_by_key(body.idempotency_key)
            if existing is not None:
                return existing
        if not is_slot_template(body.template):
            raise ApiProblem(422, f"template {body.template} is not a slot template", SLOT_HINT,
                             {"template": 101, "recipient": "yannic", "slots": {"greeting": "Good morning, Yannic"}})
        try:
            checked = validate_slots(body.template, body.slots)
        except SlotProblems as exc:
            raise ApiProblem(422, exc.problems, SLOT_HINT) from None
        now = datetime.now(settings.tzinfo)
        filled = autofill(body.template, checked.model_dump(exclude_none=True), body.recipient, now)
        if body.blocks and home_assistant() is None:
            raise ApiProblem(422, "Home Assistant is not configured", HA_HINT)
        try:
            block_lines = resolve_blocks(body.blocks, home_assistant()) if body.blocks else []
        except HAError as exc:
            raise HTTPException(status_code=502, detail=f"ticket not queued: {exc}") from None
        render_started = time.perf_counter()
        try:  # check the layout now, so a queued ticket always prints
            encode(
                ticket_lines(filled, None, template_id=body.template, sender=body.sender) + block_lines,
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
            raise ApiProblem(422, "hold and send_at cannot be combined", HOLD_HINT, {"hold": True})
        if body.hold_key and not body.hold:
            raise ApiProblem(422, "hold_key needs hold: true", HOLD_HINT, {"hold": True, "hold_key": "kitchen-briefing"})
        if body.idempotency_key:
            existing = store.get_by_key(body.idempotency_key)
            if existing is not None:
                return existing
        deadline = Deadline()  # one budget for the text clean-up and the decision, together
        choice = choose(body, deadline)
        message = prepare_text(body, deadline)
        if body.blocks and home_assistant() is None:
            raise ApiProblem(422, "Home Assistant is not configured", HA_HINT)
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
                lines = note_card_lines(message, body.sender, body.title)
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
        if body.hold and body.send_at is not None:
            raise ApiProblem(422, "hold and send_at cannot be combined", HOLD_HINT, {"hold": True})
        if body.hold_key and not held:
            raise ApiProblem(422, "hold_key needs hold: true", HOLD_HINT, {"hold": True, "hold_key": "kitchen-briefing"})
        if body.idempotency_key:
            existing = store.get_by_key(body.idempotency_key)
            if existing is not None:
                return existing
        try:
            checked = compose_validate(body.blocks)
        except BlockProblem as exc:
            raise ApiProblem(422, exc.problems, BLOCKS_HINT, COMPOSE_EXAMPLE) from None
        render_started = time.perf_counter()
        try:  # draw the strips now, so a queued ticket always prints; notes say what was shortened
            lines, notes = compose_render(checked, None)
            encode(lines, feed=template_by_id(103).feed, raster_mode=settings.raster_mode)
        except Exception as exc:
            logger.exception("composed rendering failed; ticket not queued")
            raise HTTPException(status_code=500, detail=f"rendering failed, ticket not queued: {exc}") from None
        render_ms = round((time.perf_counter() - render_started) * 1000)
        ticket = store.create(
            kind=body.kind or "note",
            tone=body.tone or DEFAULT_TONE,
            from_user=body.from_user,
            to_user=body.to_user,
            recipient=body.recipient,
            message=compose_summary(checked),
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
        return {**ticket, "notes": notes}

    @api.post("/people/{person}/release", tags=["tickets"])
    def release_person(person: Recipient, body: PersonRelease) -> dict[str, Any]:
        """Print this person's pile as strips, cutting after each. Only this person's tickets go on a strip."""
        try:
            strips = scheduler.print_release(person, body.trigger)
        except ReleaseIncomplete as exc:
            # Strips printed before the failure are already recorded; report them so nothing looks lost.
            if exc.strips:
                message = f"printed {len(exc.strips)} strip(s), then the printer failed; the rest of the pile is kept"
            else:
                message = "printer unreachable, pile kept"
            raise HTTPException(
                status_code=502,
                detail={"message": f"{message}: {exc}", "trigger": body.trigger, "strips": exc.strips},
            ) from None
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
            raise ApiProblem(422, "Home Assistant is not configured", HA_HINT)

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

    notify_limiter = NotifyLimiter()

    @api.post("/notify", tags=["settings"])
    def notify(body: NotifyIn, request: Request) -> dict[str, Any]:
        """Send a short message to Yannic's Telegram. One message per caller every 60 seconds."""
        current = read_alert_settings()
        if not (current.telegram_token and current.telegram_chat_id):
            raise ApiProblem(
                400,
                "Telegram is not configured",
                hint="Save the bot token and chat ID with PUT /api/v1/settings/alerts, then try again.",
            )
        source = request.client.host if request.client else "unknown"
        wait = notify_limiter.check(source)
        if wait > 0:
            raise HTTPException(
                status_code=429,
                detail=f"one message per minute: wait {int(wait) + 1} seconds",
                headers={"Retry-After": str(int(wait) + 1)},
            )
        text = clean_text(body.text).strip()
        if not text:
            raise ApiProblem(422, "the message is empty after removing control characters", hint="Send plain text in text.")
        try:
            send_telegram(current.telegram_token, current.telegram_chat_id, text)
        except Exception as exc:
            # The error text can carry the token. Log only the kind of error, and say nothing more to the caller.
            logger.warning("notify from %s failed: %s", source, type(exc).__name__)
            raise HTTPException(status_code=502, detail="Telegram did not accept the message. Try again later.") from None
        logger.info("notify from %s sent (%d characters)", source, len(text))
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

    @api.get("/setup/status", tags=["setup"])
    def setup_status() -> dict[str, Any]:
        """The wizard's starting values. Secrets are only reported as set or not set."""
        return {"complete": not runtime["setup_open"], **setup_flow.status_view(store, settings)}

    @api.post("/setup/check/{item}", tags=["setup"], responses={401: {"description": "Setup code is wrong"}})
    def setup_check(
        item: CheckName,
        values: SetupValues,
        x_setup_code: str | None = Header(default=None, description="The setup code from the log."),
    ) -> dict[str, Any]:
        """Test one service with the values in the wizard. Nothing is saved."""
        require_setup_code(x_setup_code)
        result = check_item(item, values)
        return {"item": item, "ok": result.ok, "detail": result.detail}

    @api.post("/setup/discover", tags=["setup"], responses={401: {"description": "Setup code is wrong"}, 422: {"description": "Network not allowed"}})
    def setup_discover(
        body: DiscoverRequest,
        x_setup_code: str | None = Header(default=None, description="The setup code from the log."),
    ) -> dict[str, Any]:
        """Look on the local network for one service. Nothing is saved, and no credentials are sent.

        Without a network, the /24 around printarr is used. Inside Docker's own range there is no home
        network to find, so the response asks for one and suggests 192.168.1.0/24.
        """
        require_setup_code(x_setup_code)
        network_text = body.network.strip() or discovery.detect_network(discovery.own_address()) or ""
        if not network_text:
            return {
                "service": body.service, "network": None, "needs_network": True,
                "suggested_network": discovery.SUGGESTED_NETWORK, "candidates": [],
            }
        try:
            network = discovery.parse_network(network_text)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        found = discovery.scan(body.service, network)
        return {
            "service": body.service, "network": str(network), "needs_network": False,
            "suggested_network": discovery.SUGGESTED_NETWORK,
            "candidates": [candidate.as_dict() for candidate in found],
        }

    @api.post("/setup/complete", tags=["setup"], responses={422: {"description": "A check failed"}})
    def setup_complete(
        values: SetupValues,
        x_setup_code: str | None = Header(default=None, description="The setup code from the log."),
    ) -> dict[str, Any]:
        """Check every service that was filled in, then save everything. Also used to change settings later.

        The first call finishes setup and opens the API. After that, the same call saves changes, and a
        blank secret keeps the saved one (list it in `clear` to remove it). A failed check returns 422
        with what to fix. Nothing is saved unless every check passes.
        """
        with setup_lock:
            require_setup_code(x_setup_code)
            values = setup_flow.fill_secrets(values, store)
            failed = {name: r.detail for name, r in run_checks(values).items() if not r.ok}
            if failed:
                raise HTTPException(status_code=422, detail=failed)
            setup_flow.save_values(store, values)
            store.set_setting(setup_flow.COMPLETE_KEY, "true")
            runtime["setup_open"] = False
            transport.swap(build_transport(setup_flow.printer_settings(settings, values)))
        logger.info("printarr settings saved")
        return {"complete": True, "restart_needed": values.timezone != settings.timezone}

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def web_ui() -> str:
        return SETUP_UI if runtime["setup_open"] else WEB_UI

    @app.get("/setup", response_class=HTMLResponse, include_in_schema=False)
    def setup_page() -> str:
        """The wizard while setup is open; afterwards the same page edits the saved settings."""
        return SETUP_UI

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
        deadline = Deadline()  # one budget for the text clean-up and the decision, together
        choice = choose(body, deadline)
        message = prepare_text(body, deadline)
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
        since_hours: int | None = Query(None, ge=1, le=SINCE_HOURS_MAX),
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
        since_hours: int | None = Query(None, ge=1, le=SINCE_HOURS_MAX),
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
        since_hours: int | None = Query(None, ge=1, le=SINCE_HOURS_MAX),
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
            cells = {**row, "decorations": ",".join(row["decorations"])}
            writer.writerow({key: _csv_safe(value) for key, value in cells.items()})
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

    @api.get("/ticket-images", tags=["tickets"])
    def list_ticket_images(limit: int = Query(50, ge=1, le=250)) -> list[dict[str, Any]]:
        """Recent tickets that have a saved PNG, newest first. Fetch one with GET /tickets/{id}/image."""
        rows = []
        for ticket_id in ticket_images.recent(settings.images_dir, limit):
            ticket = store.get(ticket_id)
            if ticket is None:  # an image whose ticket was removed from the database
                continue
            try:
                template_name = template_by_id(ticket["template_id"]).name
            except KeyError:  # a template id no longer in the code
                template_name = None
            rows.append({
                "id": ticket["id"],
                "kind": ticket["kind"],
                "template_id": ticket["template_id"],
                "template": template_name,
                "recipient": ticket["recipient"],
                "status": ticket["status"],
                "created_at": ticket["created_at"],
                "printed_at": ticket["printed_at"],
                "image_url": f"/api/v1/tickets/{ticket['id']}/image",
            })
        return rows

    @api.get(
        "/tickets/{ticket_id}/image",
        response_class=Response,
        tags=["tickets"],
        responses={200: {"content": {"image/png": {}}}},
    )
    def ticket_image(ticket_id: str) -> Response:
        """The PNG of what was sent to the printer for this ticket, from its last print or failed attempt."""
        ticket_or_404(ticket_id)
        path = ticket_images.image_path(settings.images_dir, ticket_id)
        if path is None or not path.is_file():
            raise ApiProblem(
                404,
                "no image kept for this ticket",
                hint="Images are kept for the newest tickets that reached the printer or failed there. "
                "A ticket still waiting, cancelled before printing, or older than the kept ones has none. "
                "GET /api/v1/ticket-images lists the images kept.",
            )
        return Response(content=path.read_bytes(), media_type="image/png")

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
            card = note_card_lines("If you can read this, the printer is connected.", "printarr", "Printer test")
            transport.send(encode(card, raster_mode=settings.raster_mode))
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

    @app.exception_handler(ApiProblem)
    async def _api_problem(_: Request, exc: ApiProblem) -> JSONResponse:
        body: dict[str, Any] = {"detail": exc.detail, "hint": exc.hint}
        if exc.example is not None:
            body["example"] = exc.example
        return JSONResponse(status_code=exc.status_code, content=body)

    @app.exception_handler(RequestValidationError)
    async def _invalid_request(_: Request, exc: RequestValidationError) -> JSONResponse:
        sentences = []
        for error in exc.errors():
            field = ".".join(str(part) for part in error["loc"][1:]) or "the request"
            if error["type"] == "literal_error":
                sentences.append(f"{field} must be one of {error['ctx']['expected']}.")
            else:
                sentences.append(f"{field}: {plain_message(error['msg'])}.")
        hint = " ".join([*sentences, VALIDATION_HINT])
        return JSONResponse(
            status_code=422,
            content={"detail": jsonable_encoder(exc.errors()), "hint": hint},
        )

    app.include_router(api)
    app.state.watch_printer = watch_printer  # tests and the heartbeat share this check
    return app


app = create_app()
