"""Runtime configuration, read from PRINTARR_* environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo

PRINTER_MODES = ("tcp", "file", "usb", "serial")  # usb and serial are placeholders, see printer.py
_TRUE_VALUES = ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    db_path: str = "/data/printarr.db"
    output_dir: str = "/data/output"
    timezone: str = "Europe/London"
    printer_mode: str = "tcp"
    raster_mode: str = "gs_l"  # gs_l (GS ( L fn 112) or gs_v0 (obsolete GS v 0 fallback)
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
    llm_timeout: float = 45.0  # a cold d1 load took 15.7 s and granite 8.8 s; 5 s always timed out
    backup_enabled: bool = True
    backup_hour: int = 3  # local hour for the nightly copy
    backup_keep: int = 7  # nightly copies kept
    strip_max_blocks: int = 5  # a strip is cut after this many tickets, even mid-pile
    strip_margin_dots: int = 0  # extra blank per strip; the shell margins in blocks.json already give the blank
    # Not read from the environment on purpose: the first-run wizard gate is always on in
    # production. Tests switch it off with an explicit Settings(setup_required=False).
    setup_required: bool = True

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
        raster_mode=_env("RASTER_MODE", "gs_l").lower(),
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
        llm_timeout=float(_env("LLM_TIMEOUT", "45")),
        backup_enabled=_env("BACKUP", "on").lower() in _TRUE_VALUES,
        backup_hour=int(_env("BACKUP_HOUR", "3")),
        backup_keep=int(_env("BACKUP_KEEP", "7")),
        strip_max_blocks=int(_env("STRIP_MAX_BLOCKS", "5")),
        strip_margin_dots=int(_env("STRIP_MARGIN_DOTS", "0")),
    )
    if settings.printer_mode not in PRINTER_MODES:
        raise ValueError(f"PRINTARR_PRINTER_MODE must be one of {PRINTER_MODES}")
    if settings.raster_mode not in ("gs_l", "gs_v0"):
        raise ValueError("PRINTARR_RASTER_MODE must be gs_l or gs_v0")
    if not 0 <= settings.backup_hour <= 23:
        raise ValueError("PRINTARR_BACKUP_HOUR must be 0 to 23")
    if settings.backup_keep < 1:
        raise ValueError("PRINTARR_BACKUP_KEEP must be at least 1")
    settings.tzinfo  # fails fast on an unknown timezone name
    return settings
