"""Transports that deliver ESC/POS bytes to the printer, or to files for the simulator."""

from __future__ import annotations

import socket
import threading
import time
import uuid
from pathlib import Path
from typing import Protocol

from app.config import Settings


class PrinterError(Exception):
    """The printer could not be reached or did not accept the job."""


# Real-time status requests (DLE EOT n). Answers are one byte each.
# Bit layouts for these requests are in the Command Reference (dle_eot). Checked on the real unit still pending.
STATUS_REQUESTS = (2, 3, 4)  # offline/cover, error/cutter, paper sensor


class Transport(Protocol):
    target: str

    def send(self, data: bytes) -> None: ...

    def check(self) -> None: ...

    def read_status(self) -> dict[int, int | None]: ...


class TcpTransport:
    """Raw TCP to port 9100, the usual port for Epson network printers."""

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.target = f"{host}:{port}"
        self._lock = threading.Lock()  # one job or status exchange at a time

    def send(self, data: bytes) -> None:
        with self._lock, self._connect() as sock:
            try:
                sock.sendall(data)
            except OSError as exc:
                raise PrinterError(f"write to {self.target} failed: {exc}") from exc

    def check(self) -> None:
        with self._connect():
            pass

    def read_status(self) -> dict[int, int | None]:
        """Ask the printer for its status. None means no answer for that request."""
        answers: dict[int, int | None] = {}
        with self._lock, self._connect() as sock:
            for n in STATUS_REQUESTS:
                answers[n] = None
                try:
                    sock.sendall(b"\x10\x04" + bytes([n]))
                    byte = sock.recv(1)
                    if byte:
                        answers[n] = byte[0]
                except OSError:
                    pass
        return answers

    def _connect(self) -> socket.socket:
        if not self.host:
            raise PrinterError("no printer host configured (PRINTARR_PRINTER_HOST)")
        try:
            return socket.create_connection((self.host, self.port), timeout=self.timeout)
        except OSError as exc:
            raise PrinterError(f"cannot reach printer at {self.target}: {exc}") from exc


class FileTransport:
    """Writes each job to its own .bin file. Used for tests and the simulator."""

    def __init__(self, output_dir: str) -> None:
        self.output_dir = Path(output_dir)
        self.target = str(self.output_dir)

    def send(self, data: bytes) -> None:
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            name = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}.bin"
            (self.output_dir / name).write_bytes(data)
        except OSError as exc:
            raise PrinterError(f"cannot write to {self.target}: {exc}") from exc

    def check(self) -> None:
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise PrinterError(f"cannot use {self.target}: {exc}") from exc

    def read_status(self) -> dict[int, int | None]:
        return {n: 0 for n in STATUS_REQUESTS}  # a file has no paper, cover or cutter


def build_transport(settings: Settings) -> Transport:
    if settings.printer_mode == "file":
        return FileTransport(settings.output_dir)
    return TcpTransport(settings.printer_host, settings.printer_port, settings.printer_timeout)
