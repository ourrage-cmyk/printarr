"""First-run setup: the checks behind the wizard, and where its answers are stored.

Until the wizard finishes, the API answers only the setup routes and health (see main.py).
Secrets, the Home Assistant token and the Telegram token, are typed into the wizard and kept in
the SQLite database in the data folder. They never come from environment variables or the
compose file, and no endpoint returns them: responses say "set" or "not set".

The setup code is random, printed to the log at each start until setup is finished, and kept
only as a hash. Every wizard request must send it in the X-Setup-Code header.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field

from app.alerts import send_telegram
from app.config import Settings
from app.ha import HAClient, HAError
from app.printer import PrinterError, TcpTransport

COMPLETE_KEY = "setup_complete"
CODE_HASH_KEY = "setup_code_hash"
CHECK_TIMEOUT = 5.0  # seconds per check; the wizard waits for each one

CheckName = Literal["home_assistant", "model_server", "printer", "telegram", "timezone"]
CHECK_NAMES = ("home_assistant", "model_server", "printer", "telegram", "timezone")

# Keys read back by stored_overrides() at start-up. Others are read through the store.
OVERRIDE_KEYS = ("printer_host", "printer_port", "timezone")


class SetupValues(BaseModel):
    """Everything the wizard collects. Blank secrets and URLs mean "not used"."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    timezone: str = Field(default="Europe/London", max_length=60, examples=["Europe/London"])
    printer_host: str = Field(default="", max_length=200, examples=["192.168.1.50"])
    printer_port: int = Field(default=9100, ge=1, le=65535)
    ha_url: str = Field(default="", max_length=300, examples=["http://192.168.1.10:8123"])
    ha_token: str = Field(default="", max_length=500, description="Home Assistant long-lived access token. Stored, never returned.")
    llm_enabled: bool = True
    llm_base_url: str = Field(default="", max_length=300, examples=["http://192.0.2.231:11434/v1"])
    llm_model: str = Field(default="d1:latest", max_length=120)
    llm_text_model: str = Field(default="granite4.2:3b", max_length=120)
    telegram_token: str = Field(default="", max_length=200, description="Telegram bot token. Stored, never returned.")
    telegram_chat_id: str = Field(default="", max_length=50)
    yannic_name: str = Field(default="Yannic", min_length=1, max_length=40)
    wife_name: str = Field(default="Allyson", min_length=1, max_length=40)
    clear: list[Literal["ha_token", "telegram_token"]] = Field(
        default_factory=list,
        description="Secrets to remove. A blank secret keeps the saved one, so use this to clear it.",
    )


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    detail: str


def new_code() -> str:
    return secrets.token_urlsafe(12)


def code_hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def code_matches(code: str | None, stored_hash: str | None) -> bool:
    if not code or not stored_hash:
        return False
    return hmac.compare_digest(code_hash(code), stored_hash)


def _is_http_url(url: str) -> bool:
    parts = urllib.parse.urlsplit(url)
    return parts.scheme in ("http", "https") and bool(parts.netloc)


def check_home_assistant(url: str, token: str) -> CheckResult:
    if not _is_http_url(url):
        return CheckResult(False, "The Home Assistant address must start with http:// or https://.")
    if not token:
        return CheckResult(False, "Paste the long-lived access token.")
    try:
        HAClient(url, token, timeout=CHECK_TIMEOUT).ping()
    except HAError as exc:
        return CheckResult(False, str(exc))
    return CheckResult(True, "Home Assistant answered and accepted the token.")


def check_model_server(base_url: str, models: list[str]) -> CheckResult:
    if not _is_http_url(base_url):
        return CheckResult(False, "The model server address must start with http:// or https://.")
    try:
        with urllib.request.urlopen(base_url.rstrip("/") + "/models", timeout=CHECK_TIMEOUT) as response:
            data = json.loads(response.read())
    except (OSError, ValueError):
        return CheckResult(False, f"Cannot reach a model server at {base_url}.")
    available = {
        str(item.get("id", "")) for item in data.get("data", []) if isinstance(item, dict)
    }
    missing = [name for name in models if name and name not in available]
    if missing:
        listed = ", ".join(sorted(available)[:12]) or "none"
        return CheckResult(False, f"Not on the server: {', '.join(missing)}. The server has: {listed}.")
    return CheckResult(True, "Model server answered and has both models.")


def check_printer(host: str, port: int) -> CheckResult:
    if not host:
        return CheckResult(False, "Enter the printer's IP address, or the simulator's.")
    try:
        TcpTransport(host, port, CHECK_TIMEOUT).check()
    except PrinterError as exc:
        return CheckResult(False, str(exc))
    return CheckResult(True, f"Connected to {host}:{port}.")


def check_telegram(token: str, chat_id: str) -> CheckResult:
    if not token:
        return CheckResult(False, "Paste the bot token from BotFather.")
    try:
        with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/getMe", timeout=CHECK_TIMEOUT) as response:
            if response.status != 200:
                return CheckResult(False, f"Telegram returned HTTP {response.status}.")
    except Exception as exc:  # the token is in the URL, so never echo the raw error
        message = str(exc).replace(token, "<token>")
        return CheckResult(False, f"Telegram did not accept the bot token: {message}")
    if not chat_id:
        return CheckResult(True, "Bot token accepted. Add a chat ID to get alerts.")
    try:
        send_telegram(token, chat_id, "Printarr setup check: alerts will arrive in this chat.")
    except Exception as exc:
        return CheckResult(False, str(exc))
    return CheckResult(True, "Bot token accepted and a test message was sent.")


def check_timezone(name: str) -> CheckResult:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return CheckResult(False, f"'{name}' is not a timezone name such as Europe/London.")
    return CheckResult(True, "Timezone is valid.")


def check_item(item: CheckName, values: SetupValues) -> CheckResult:
    if item == "home_assistant":
        return check_home_assistant(values.ha_url, values.ha_token)
    if item == "model_server":
        if not values.llm_enabled:
            return CheckResult(True, "Model server is switched off, so the fixed rules pick templates.")
        return check_model_server(values.llm_base_url, [values.llm_model, values.llm_text_model])
    if item == "printer":
        return check_printer(values.printer_host, values.printer_port)
    if item == "telegram":
        return check_telegram(values.telegram_token, values.telegram_chat_id)
    return check_timezone(values.timezone)


def run_checks(values: SetupValues) -> dict[str, CheckResult]:
    """Check the printer and timezone always, and each optional service that was filled in."""
    results = {"printer": check_item("printer", values), "timezone": check_item("timezone", values)}
    if values.ha_url or values.ha_token:
        results["home_assistant"] = check_item("home_assistant", values)
    if values.llm_enabled and values.llm_base_url:
        results["model_server"] = check_item("model_server", values)
    if values.telegram_token or values.telegram_chat_id:
        results["telegram"] = check_item("telegram", values)
    return results


# Setting key for each wizard field. Same keys the Settings endpoints already use.
SAVED_KEYS: dict[str, str] = {
    "timezone": "timezone",
    "printer_host": "printer_host",
    "printer_port": "printer_port",
    "ha_url": "ha_url",
    "ha_token": "ha_token",
    "llm_enabled": "llm_enabled",
    "llm_base_url": "llm_base_url",
    "llm_model": "llm_model",
    "llm_text_model": "llm_text_model",
    "telegram_token": "alert_telegram_token",
    "telegram_chat_id": "alert_telegram_chat_id",
    "yannic_name": "recipient_name_yannic",
    "wife_name": "recipient_name_wife",
}
SECRET_FIELDS = ("ha_token", "telegram_token")


def fill_secrets(values: SetupValues, store) -> SetupValues:
    """Keep a saved secret when its box is blank, unless it is listed in `clear`."""
    update: dict[str, str] = {}
    for field in SECRET_FIELDS:
        if field in values.clear:
            update[field] = ""
        elif not getattr(values, field):
            update[field] = store.get_setting(SAVED_KEYS[field]) or ""
    return values.model_copy(update=update) if update else values


def save_values(store, values: SetupValues) -> None:
    for field, key in SAVED_KEYS.items():
        value = getattr(values, field)
        if isinstance(value, bool):
            value = "true" if value else "false"
        store.set_setting(key, str(value))


def status_view(store, settings: Settings) -> dict:
    """What the wizard shows: non-secret values as saved (or defaults), and set / not set for secrets."""
    defaults = SetupValues(
        timezone=settings.timezone,
        printer_host=settings.printer_host,
        printer_port=settings.printer_port,
        llm_enabled=settings.llm_enabled,
        llm_base_url=settings.llm_base_url,
        llm_model=settings.llm_model,
        llm_text_model=settings.llm_text_model,
    )
    fields: dict[str, object] = {}
    for field, key in SAVED_KEYS.items():
        if field in SECRET_FIELDS:
            continue
        saved = store.get_setting(key)
        if saved is None:
            fields[field] = getattr(defaults, field)
        elif field == "llm_enabled":
            fields[field] = saved.lower() == "true"
        elif field == "printer_port":
            fields[field] = int(saved)
        else:
            fields[field] = saved
    secrets_set = {
        field: "set" if store.get_setting(SAVED_KEYS[field]) else "not set" for field in SECRET_FIELDS
    }
    return {"fields": fields, "secrets": secrets_set}


def stored_overrides(settings: Settings) -> Settings:
    """Apply printer and timezone saved by the wizard, read without writing the database.

    Runs before the store is opened, so a fresh install with no database file keeps the
    environment values. Legacy installs without these keys keep their environment too.
    """
    path = Path(settings.db_path)
    if not path.exists():
        return settings
    try:
        conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
        try:
            placeholders = ",".join("?" * len(OVERRIDE_KEYS))
            rows = dict(
                conn.execute(f"SELECT key, value FROM settings WHERE key IN ({placeholders})", OVERRIDE_KEYS).fetchall()
            )
        finally:
            conn.close()
    except sqlite3.Error:
        return settings
    changes: dict[str, object] = {}
    if rows.get("printer_host"):
        changes.update(
            printer_mode="tcp",
            printer_host=rows["printer_host"],
            printer_port=int(rows.get("printer_port") or settings.printer_port),
        )
    if rows.get("timezone"):
        changes["timezone"] = rows["timezone"]
    return replace(settings, **changes) if changes else settings


def is_legacy_install(store) -> bool:
    """An install from before the wizard already has model settings in its database."""
    return store.get_setting("llm_enabled") is not None


def printer_settings(settings: Settings, values: SetupValues) -> Settings:
    return replace(settings, printer_mode="tcp", printer_host=values.printer_host, printer_port=values.printer_port)


def make_private(path: str) -> None:
    """Best effort: keep the database readable by its owner only."""
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
