"""Transports that deliver ESC/POS bytes to the printer, or to files for the simulator.

Every job goes through one Transport. The scheduler is the only caller of send() for
tickets, so jobs reach the printer one at a time.
"""

from __future__ import annotations

import socket
import threading
import time
import uuid
from pathlib import Path
from typing import Protocol

from app.config import Settings

# Bytes per write. TCP flow control still applies per write. Small writes mean a failure
# reports how much of the job had been handed over.
CHUNK_BYTES = 4096
# A status request that gets no answer within this many seconds is reported as None.
STATUS_TIMEOUT = 1.0

# Real-time status requests (DLE EOT n). Answers are one byte each. Bit layouts are in app/status.py.
STATUS_REQUESTS = (1, 2, 3, 4)  # printer status, offline cause, error cause, paper sensor


class PrinterError(Exception):
    """The printer could not be reached or did not accept the job."""


class PrintInterrupted(PrinterError):
    """The connection failed part-way through a job. `bytes_sent` is how much was written."""

    def __init__(self, message: str, bytes_sent: int) -> None:
        super().__init__(message)
        self.bytes_sent = bytes_sent


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
        """Write the job in chunks. Raises PrintInterrupted if the connection drops part-way."""
        with self._lock, self._connect() as sock:
            sent = 0
            try:
                for start in range(0, len(data), CHUNK_BYTES):
                    chunk = data[start : start + CHUNK_BYTES]
                    sock.sendall(chunk)
                    sent += len(chunk)
            except OSError as exc:
                raise PrintInterrupted(
                    f"write to {self.target} failed after {sent} of {len(data)} bytes: {exc}", sent
                ) from exc

    def check(self) -> None:
        with self._connect():
            pass

    def read_status(self) -> dict[int, int | None]:
        """Ask the printer for its status. None means no answer for that request."""
        answers: dict[int, int | None] = {}
        with self._lock, self._connect() as sock:
            sock.settimeout(min(self.timeout, STATUS_TIMEOUT))
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


class UnbuiltTransport:
    """Placeholder for connections that are not built yet (USB, serial).

    Every call fails with a clear message, so health shows the printer as unreachable
    instead of silently dropping jobs.
    """

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self.target = kind

    def _fail(self) -> None:
        raise PrinterError(f"{self.kind} printer connection is not built yet; use PRINTARR_PRINTER_MODE=tcp")

    def send(self, data: bytes) -> None:
        self._fail()

    def check(self) -> None:
        self._fail()

    def read_status(self) -> dict[int, int | None]:
        self._fail()
        return {}  # not reached


def build_transport(settings: Settings) -> Transport:
    if settings.printer_mode == "file":
        return FileTransport(settings.output_dir)
    if settings.printer_mode in ("usb", "serial"):
        return UnbuiltTransport(settings.printer_mode)
    return TcpTransport(settings.printer_host, settings.printer_port, settings.printer_timeout)
