import ipaddress
import json
import socket
import socketserver
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from fastapi.testclient import TestClient

from app import discovery
from app.main import create_app


class _Handler(BaseHTTPRequestHandler):
    routes: dict[str, object] = {}

    def do_GET(self):
        body = self.routes.get(self.path)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        payload = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):  # keep test output quiet
        pass


def _serve_http(routes: dict[str, object]):
    handler = type("Handler", (_Handler,), {"routes": routes})
    server = HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class _PrinterSim(socketserver.ThreadingTCPServer):
    allow_reuse_address = True


def _serve_printer():
    class Printer(socketserver.BaseRequestHandler):
        def handle(self):
            data = self.request.recv(16)
            if data == b"\x10\x04\x01":
                self.request.sendall(b"\x12")  # the simulator's status byte

    server = _PrinterSim(("127.0.0.1", 0), Printer)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _closed_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def loopback():
    servers = []

    def make(service, routes=None):
        if service == "printer":
            server = _serve_printer()
        else:
            server = _serve_http(routes or {})
        servers.append(server)
        return server.server_address[1]

    yield make
    for server in servers:
        server.shutdown()
        server.server_close()


def one_host() -> ipaddress.IPv4Network:
    return ipaddress.ip_network("127.0.0.1/32")


def test_home_assistant_is_found_by_its_manifest(loopback):
    port = loopback("home_assistant", {"/manifest.json": {"name": "Home Assistant", "short_name": "Assist"}})
    found = discovery.scan("home_assistant", one_host(), port=port)
    assert len(found) == 1 and found[0].verified
    assert found[0].url == f"http://127.0.0.1:{port}"


def test_other_web_servers_are_not_home_assistant(loopback):
    port = loopback("home_assistant", {"/manifest.json": {"name": "Some other app"}})
    assert discovery.scan("home_assistant", one_host(), port=port) == []


def test_printer_that_answers_its_status_is_verified(loopback):
    port = loopback("printer")
    found = discovery.scan("printer", one_host(), port=port)
    assert len(found) == 1 and found[0].verified
    assert "answers its status request" in found[0].detail


def test_open_port_without_status_reply_is_a_weaker_candidate(loopback):
    silent = socketserver.ThreadingTCPServer(("127.0.0.1", 0), socketserver.BaseRequestHandler)
    threading.Thread(target=silent.serve_forever, daemon=True).start()
    try:
        found = discovery.scan("printer", one_host(), port=silent.server_address[1])
        assert len(found) == 1 and found[0].verified is False
    finally:
        silent.shutdown()
        silent.server_close()


def test_ollama_lists_its_models(loopback):
    tags = {"models": [{"name": "granite4.2:3b"}, {"name": "d1:latest"}, {"name": "llama3:8b"}]}
    port = loopback("model_server", {"/api/tags": tags})
    found = discovery.scan("model_server", one_host(), port=port)
    assert len(found) == 1
    assert found[0].url == f"http://127.0.0.1:{port}/v1"
    assert found[0].models == ("d1:latest", "granite4.2:3b", "llama3:8b")
    assert "including d1:latest, granite4.2:3b" in found[0].detail


def test_closed_ports_find_nothing():
    assert discovery.scan("printer", one_host(), port=_closed_port()) == []


def test_only_private_networks_can_be_scanned():
    assert str(discovery.parse_network("192.168.1.77/24")) == "192.168.1.0/24"
    with pytest.raises(ValueError):
        discovery.parse_network("8.8.8.0/24")
    with pytest.raises(ValueError):
        discovery.parse_network("192.168.0.0/16")
    with pytest.raises(ValueError):
        discovery.parse_network("not a network")


def test_docker_range_asks_for_the_home_network_instead():
    assert discovery.detect_network("172.17.0.5") is None
    assert discovery.detect_network("192.168.1.50") == "192.168.1.0/24"
    assert discovery.detect_network(None) is None


def test_discover_endpoint_needs_the_setup_code(settings):
    from dataclasses import replace

    with TestClient(create_app(replace(settings, setup_required=True))) as client:
        response = client.post("/api/v1/setup/discover", json={"service": "printer"}, headers={"X-Setup-Code": "guess"})
        assert response.status_code == 401


def test_discover_endpoint_asks_for_a_network_inside_docker(settings, monkeypatch):
    from dataclasses import replace

    monkeypatch.setattr(discovery, "own_address", lambda: "172.17.0.2")
    app = create_app(replace(settings, setup_required=True))
    with TestClient(app) as client:
        body = client.post(
            "/api/v1/setup/discover",
            json={"service": "printer"},
            headers={"X-Setup-Code": app.state.setup_code},
        ).json()
        assert body["needs_network"] is True and body["suggested_network"] == "192.168.1.0/24"
        assert body["candidates"] == []


def test_discover_endpoint_returns_candidates_and_saves_nothing(settings, monkeypatch, loopback):
    from dataclasses import replace

    from app.store import TicketStore

    port = loopback("printer")
    monkeypatch.setitem(discovery.DEFAULT_PORTS, "printer", port)
    app = create_app(replace(settings, setup_required=True))
    with TestClient(app) as client:
        body = client.post(
            "/api/v1/setup/discover",
            json={"service": "printer", "network": "127.0.0.1/32"},
            headers={"X-Setup-Code": app.state.setup_code},
        ).json()
        assert body["needs_network"] is False and body["network"] == "127.0.0.1/32"
        assert body["candidates"][0]["host"] == "127.0.0.1" and body["candidates"][0]["port"] == port
        assert TicketStore(settings.db_path).get_setting("printer_host") is None


def test_discover_endpoint_refuses_public_networks(settings):
    from dataclasses import replace

    app = create_app(replace(settings, setup_required=True))
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/setup/discover",
            json={"service": "printer", "network": "8.8.8.0/24"},
            headers={"X-Setup-Code": app.state.setup_code},
        )
        assert response.status_code == 422
