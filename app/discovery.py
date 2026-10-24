"""Find Home Assistant, the printer and the model server on the local network.

The wizard's Scan buttons call this. It only looks at private IPv4 networks, and it sends no
credentials: each probe asks a question a service answers without a login, and the answer tells
which service it is. Nothing is saved. The wizard fills in a candidate, and the Test button still
decides whether it works.
"""

from __future__ import annotations

import http.client
import ipaddress
import json
import socket
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass
from typing import Callable, Literal

from pydantic import BaseModel, ConfigDict, Field

Service = Literal["home_assistant", "printer", "model_server"]
DEFAULT_PORTS: dict[str, int] = {"home_assistant": 8123, "printer": 9100, "model_server": 11434}
SUGGESTED_NETWORK = "192.168.1.0/24"
PREFERRED_MODELS = ("d1:latest", "granite4.2:3b")
MAX_ADDRESSES = 1024  # a /22 at most, so a scan stays quick
CONNECT_TIMEOUT = 0.5  # seconds to open a port on one host
REPLY_TIMEOUT = 1.5  # seconds to wait for a reply
SCAN_DEADLINE = 25.0  # seconds for a whole scan, whatever is still running
DOCKER_RANGE = ipaddress.ip_network("172.16.0.0/12")  # Docker's bridge networks live here
PRINTER_STATUS_REQUEST = b"\x10\x04\x01"  # DLE EOT 1: ask for the printer status


class DiscoverRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service: Service
    network: str = Field(
        default="",
        max_length=40,
        description="Network to scan, such as 192.168.1.0/24. Blank uses the network around this printarr.",
        examples=["192.168.1.0/24"],
    )


@dataclass(frozen=True)
class Candidate:
    service: str
    host: str
    port: int
    detail: str
    url: str = ""
    verified: bool = False  # the service answered the question that identifies it
    models: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return asdict(self)


def own_address() -> str | None:
    """The address this container sends from. No packet is sent: a UDP connect only picks the route."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("10.255.255.255", 1))
            return sock.getsockname()[0]
    except OSError:
        return None


def detect_network(address: str | None) -> str | None:
    """The /24 around this container's address. None when it sits in Docker's range, since that is not the home network."""
    if not address:
        return None
    if ipaddress.ip_address(address) in DOCKER_RANGE:
        return None
    return str(ipaddress.ip_network(f"{address}/24", strict=False))


def parse_network(text: str) -> ipaddress.IPv4Network:
    try:
        network = ipaddress.ip_network(text.strip(), strict=False)
    except ValueError as exc:
        raise ValueError("Enter a network such as 192.168.1.0/24.") from exc
    if network.version != 4 or not network.is_private:
        raise ValueError("Only private IPv4 networks such as 192.168.1.0/24 can be scanned.")
    if network.num_addresses > MAX_ADDRESSES:
        raise ValueError("Use a smaller network, /22 or smaller, so the scan stays quick.")
    return network


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=CONNECT_TIMEOUT):
            return True
    except OSError:
        return False


def _get_json(host: str, port: int, path: str) -> object | None:
    """A plain GET with no credentials. Anything but a 200 with JSON counts as no answer."""
    conn = http.client.HTTPConnection(host, port, timeout=REPLY_TIMEOUT)
    try:
        conn.request("GET", path, headers={"Accept": "application/json"})
        response = conn.getresponse()
        if response.status != 200:
            return None
        return json.loads(response.read(200_000))
    except (OSError, ValueError, http.client.HTTPException):
        return None
    finally:
        conn.close()


def probe_home_assistant(host: str, port: int) -> Candidate | None:
    if not _port_open(host, port):
        return None
    manifest = _get_json(host, port, "/manifest.json")
    if not isinstance(manifest, dict) or manifest.get("name") != "Home Assistant":
        return None
    return Candidate(
        "home_assistant", host, port, detail=f"Home Assistant at {host}:{port}",
        url=f"http://{host}:{port}", verified=True,
    )


def probe_printer(host: str, port: int) -> Candidate | None:
    try:
        sock = socket.create_connection((host, port), timeout=CONNECT_TIMEOUT)
    except OSError:
        return None
    with sock:
        sock.settimeout(REPLY_TIMEOUT)
        try:
            sock.sendall(PRINTER_STATUS_REQUEST)
            reply = sock.recv(1)
        except OSError:
            reply = b""
    answered = len(reply) == 1
    note = "answers its status request" if answered else "port open, no status reply"
    return Candidate("printer", host, port, detail=f"Printer at {host}:{port}, {note}", verified=answered)


def probe_model_server(host: str, port: int) -> Candidate | None:
    tags = _get_json(host, port, "/api/tags")
    if not isinstance(tags, dict) or not isinstance(tags.get("models"), list):
        return None
    names = tuple(sorted({str(m["name"]) for m in tags["models"] if isinstance(m, dict) and m.get("name")}))
    found = [name for name in PREFERRED_MODELS if name in names]
    note = f"{len(names)} models" + (f", including {', '.join(found)}" if found else "")
    return Candidate(
        "model_server", host, port, detail=f"Ollama at {host}:{port}, {note}",
        url=f"http://{host}:{port}/v1", verified=True, models=names,
    )


PROBES: dict[str, Callable[[str, int], Candidate | None]] = {
    "home_assistant": probe_home_assistant,
    "printer": probe_printer,
    "model_server": probe_model_server,
}


def scan(service: str, network: ipaddress.IPv4Network, port: int | None = None, workers: int = 64) -> list[Candidate]:
    """Probe every address in the network for one service. Verified answers come first."""
    probe = PROBES[service]
    port = DEFAULT_PORTS[service] if port is None else port
    hosts = list(network.hosts()) or list(network)
    found: list[Candidate] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(probe, str(host), port) for host in hosts]
        done, pending = wait(futures, timeout=SCAN_DEADLINE)
        for future in pending:
            future.cancel()
        for future in done:
            try:
                result = future.result()
            except Exception:  # one bad host never stops the scan
                result = None
            if result is not None:
                found.append(result)
    found.sort(key=lambda c: (not c.verified, ipaddress.ip_address(c.host)))
    return found
