"""A fake TM-T88V on a local TCP port, for tests.

It records each job it receives and answers DLE EOT status requests from a table the
test can change. Faults can be injected: a status request left unanswered, a job
connection dropped after N bytes, or the whole printer powered off and on again.

A connection that starts with DLE EOT is a status session. Anything else is a job.
"""

from __future__ import annotations

import socket
import socketserver
import struct
import threading

from app.printer import TcpTransport

DLE_EOT = b"\x10\x04"


class _Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        printer: FakePrinter = self.server.printer  # type: ignore[attr-defined]
        first = self.request.recv(65536)
        if not first:
            return
        if first.startswith(DLE_EOT):
            self._status_session(printer, first)
        else:
            self._job_session(printer, first)

    def _status_session(self, printer: FakePrinter, data: bytes) -> None:
        while data:
            # Each request is three bytes: DLE EOT n. The client waits for one reply each time.
            for start in range(0, len(data) - 2, 3):
                if data[start : start + 2] != DLE_EOT:
                    continue
                n = data[start + 2]
                value = printer.status.get(n)
                if value is not None:
                    self.request.sendall(bytes([value]))
            data = self.request.recv(65536)

    def _job_session(self, printer: FakePrinter, first: bytes) -> None:
        job = bytearray(first)
        limit = printer.drop_job_after
        while True:
            if limit is not None and len(job) >= limit:
                # Power loss or cable pull: hang up with unread data, so the sender sees a reset.
                self.request.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
                printer.partial_jobs.append(bytes(job))
                return
            data = self.request.recv(65536)
            if not data:
                break
            job += data
        printer.jobs.append(bytes(job))


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def server_bind(self) -> None:
        # A small receive buffer means a dropped job cannot be swallowed by the kernel.
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
        super().server_bind()


class FakePrinter:
    def __init__(self, port: int = 0) -> None:
        self.status: dict[int, int | None] = {1: 0x12, 2: 0x12, 3: 0x12, 4: 0x12}
        self.drop_job_after: int | None = None
        self.jobs: list[bytes] = []  # jobs that reached the end
        self.partial_jobs: list[bytes] = []  # jobs cut off by a fault
        self._port = port
        self._server: _Server | None = None
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return self._port  # kept across power cycles, so a restarted printer answers on the same port

    def start(self) -> FakePrinter:
        """Power on (or back on, on the same port) and begin accepting connections."""
        self._server = _Server(("127.0.0.1", self._port), _Handler)
        self._server.printer = self  # type: ignore[attr-defined]
        self._port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        """Power off. Connections are refused until start() is called again."""
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    def transport(self, timeout: float = 2.0) -> TcpTransport:
        return TcpTransport("127.0.0.1", self.port, timeout)

    def __enter__(self) -> FakePrinter:
        return self.start()

    def __exit__(self, *exc_info) -> None:
        self.stop()
