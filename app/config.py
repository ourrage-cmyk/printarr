"""Runtime configuration, read from PRINTARR_* environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo

PRINTER_MODES = ("tcp", "file")
_TRUE_VALUES = ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    db_path: str = "/data/printarr.db"
    output_dir: str = "/data/output"
    timezone: str = "Europe/London"
    printer_mode: str = "tcp"
    printer_host: str = ""
    printer_port: int = 9100
    printer_timeout: float = 5.0
    paper_width: int = 42
    poll_interval: float = 5.0
    max_attempts: int = 5
    retry_base_seconds: int = 30
    scheduler_enabled: bool = True
    llm_enabled: bool = True
    llm_base_url: str = ""
    llm_model: str = "d1:latest"  # decision model: template and decoration choice only
    llm_text_model: str = "granite4.2:3b"  # text model: for paragraphs, later
    llm_timeout: float = 5.0

    @property
    def tzinfo(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


def _env(name: str, default: str) -> str:
    return os.environ.get(f"PRINTARR_{name}", default).strip()


def load_settings() -> Settings:
    settings = Settings(
        db_path=_env("DB_PATH", "/data/printarr.db"),
        output_dir=_env("OUTPUT_DIR", "/data/output"),
        timezone=_env("TIMEZONE", "Europe/London"),
        printer_mode=_env("PRINTER_MODE", "tcp").lower(),
        printer_host=_env("PRINTER_HOST", ""),
        printer_port=int(_env("PRINTER_PORT", "9100")),
        printer_timeout=float(_env("PRINTER_TIMEOUT", "5")),
        paper_width=int(_env("PAPER_WIDTH", "42")),
        poll_interval=float(_env("POLL_INTERVAL", "5")),
        max_attempts=int(_env("MAX_ATTEMPTS", "5")),
        retry_base_seconds=int(_env("RETRY_BASE_SECONDS", "30")),
        scheduler_enabled=_env("SCHEDULER", "on").lower() in _TRUE_VALUES,
        llm_enabled=_env("LLM_ENABLED", "on").lower() in _TRUE_VALUES,
        llm_base_url=_env("LLM_BASE_URL", ""),
        llm_model=_env("LLM_MODEL", "d1:latest"),
        llm_text_model=_env("LLM_TEXT_MODEL", "granite4.2:3b"),
        llm_timeout=float(_env("LLM_TIMEOUT", "5")),
    )
    if settings.printer_mode not in PRINTER_MODES:
        raise ValueError(f"PRINTARR_PRINTER_MODE must be one of {PRINTER_MODES}")
    settings.tzinfo  # fails fast on an unknown timezone name
    return settings
