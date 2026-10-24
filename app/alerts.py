"""Outbound alerts (Telegram) and the Uptime Kuma heartbeat.

Alerts fire once when a problem starts and once more when it clears, so a printer that
stays down does not send a message every few seconds.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

logger = logging.getLogger("printarr.alerts")


@dataclass(frozen=True)
class AlertSettings:
    telegram_token: str = ""
    telegram_chat_id: str = ""


def send_telegram(token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = json.dumps({"chat_id": chat_id, "text": text}).encode()
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            if response.status != 200:
                raise RuntimeError(f"Telegram returned HTTP {response.status}")
    except Exception as exc:
        # The bot token is part of the URL, so an error message can carry it. Strip it, and drop
        # the chained original so no traceback printed later can show it either.
        message = str(exc).replace(token, "<token>") if token else str(exc)
        raise RuntimeError(f"Telegram send failed: {message}") from None


def describe_failure(exc: BaseException, where: str, timeout: float | None = None) -> str:
    """Say what went wrong, with the real cause: the HTTP status, the timeout, or the network error."""
    if isinstance(exc, urllib.error.HTTPError):
        try:
            detail = exc.read(200).decode("utf-8", "replace").strip()
        except Exception:  # the body is optional: the status alone still says what happened
            detail = ""
        return f"{where} answered HTTP {exc.code} {exc.reason}" + (f": {detail}" if detail else "")
    if isinstance(exc, TimeoutError) or (isinstance(exc, urllib.error.URLError) and isinstance(exc.reason, TimeoutError)):
        limit = f" within {timeout:g} s" if timeout else ""
        return f"{where} gave no answer{limit} (timeout)"
    if isinstance(exc, urllib.error.URLError):
        return f"{where} cannot be reached: {exc.reason}"
    return f"{where} failed: {type(exc).__name__}: {exc}"


REPEATS_TO_ALERT = 3  # a model alert needs this many failures...
REPEAT_WINDOW_S = 900.0  # ...inside this window, so one slow answer never pages anyone


class Notifier:
    def __init__(
        self,
        read_settings: Callable[[], AlertSettings],
        sender: Callable[[str, str, str], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._read = read_settings
        self._sender = sender or send_telegram
        self._clock = clock
        self._active: set[str] = set()
        self._failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def is_active(self, key: str) -> bool:
        with self._lock:
            return key in self._active

    def problem(self, key: str, text: str) -> None:
        """Alert once for this key. Repeats are suppressed until recovered()."""
        logger.error(text)
        if not self._configured():
            return  # nothing could be sent, so the next event must still alert
        with self._lock:
            if key in self._active:
                return
            self._active.add(key)
        self._send(f"Printarr alert: {text}")

    def repeated(self, key: str, text: str) -> None:
        """Log every failure, but alert only when REPEATS_TO_ALERT of them fall within REPEAT_WINDOW_S."""
        logger.warning(text)
        now = self._clock()
        with self._lock:
            recent = [t for t in self._failures.get(key, []) if now - t < REPEAT_WINDOW_S]
            recent.append(now)
            self._failures[key] = recent
            due = len(recent) >= REPEATS_TO_ALERT
        if due:
            self.problem(key, text)

    def clear_failures(self, key: str) -> None:
        """A success: forget the failures counted so far."""
        with self._lock:
            self._failures.pop(key, None)

    def recovered(self, key: str, text: str) -> None:
        self.clear_failures(key)
        with self._lock:
            if key not in self._active:
                return
            self._active.discard(key)
        logger.info(text)
        self._send(f"Printarr recovered: {text}")

    def send_now(self, text: str) -> None:
        """Send without de-duplication, for tests and one-off messages."""
        self._send(text)

    def _configured(self) -> bool:
        settings = self._read()
        return bool(settings.telegram_token and settings.telegram_chat_id)

    def _send(self, text: str) -> None:
        settings = self._read()
        if not (settings.telegram_token and settings.telegram_chat_id):
            return
        try:
            self._sender(settings.telegram_token, settings.telegram_chat_id, text)
        except Exception as exc:
            logger.error("could not send Telegram alert: %s", exc)


class HeartbeatThread:
    """Runs the printer and health checks every `interval` seconds. Nothing is pushed out."""

    def __init__(self, tick: Callable[[], None], interval: float = 60.0) -> None:
        self._tick = tick
        self._interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="printarr-heartbeat", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=10)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception:
                logger.exception("heartbeat tick failed")
            self._stop.wait(self._interval)
