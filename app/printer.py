"""Transports that deliver ESC/POS bytes to the printer, or to files for the simulator."""

from __future__ import annotations

import socket
import time
import uuid
from pathlib import Path
from typing import Protocol

from app.config import Settings


class PrinterError(Exception):
    """The printer could not be reached or did not accept the job."""


class Transport(Protocol):
    target: str

    def send(self, data: bytes) -> None: ...

    def check(self) -> None: ...


class TcpTransport:
    """Raw TCP to port 9100, the usual port for Epson network printers."""

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.target = f"{host}:{port}"

    def send(self, data: bytes) -> None:
        with self._connect() as sock:
            try:
                sock.sendall(data)
            except OSError as exc:
                raise PrinterError(f"write to {self.target} failed: {exc}") from exc

    def check(self) -> None:
        with self._connect():
            pass

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


def build_transport(settings: Settings) -> Transport:
    if settings.printer_mode == "file":
        return FileTransport(settings.output_dir)
    return TcpTransport(settings.printer_host, settings.printer_port, settings.printer_timeout)
