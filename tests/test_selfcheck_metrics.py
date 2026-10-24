"""Self-check and metrics endpoints, against the fake printer and the file printer."""

from dataclasses import replace

from fastapi.testclient import TestClient

from app.main import create_app
from tests.fake_printer import FakePrinter


def test_self_check_on_file_printer_is_clear(settings):
    with TestClient(create_app(settings)) as client:
        body = client.get("/api/v1/printer/self-check").json()
    assert body["reachable"] is True
    assert body["faults"] == []
    assert body["unanswered"] == []


def test_self_check_reports_cover_open_without_printing(settings):
    with FakePrinter() as fake:
        fake.status[2] = 0x12 | 0x04
        tcp = replace(settings, printer_mode="tcp", printer_host="127.0.0.1", printer_port=fake.port,
                      printer_timeout=2)
        with TestClient(create_app(tcp)) as client:
            body = client.get("/api/v1/printer/self-check").json()
    assert body["reachable"] is True
    assert body["faults"] == ["cover"]
    assert body["queue_paused"] is None  # the check does not touch the queue
    assert fake.jobs == []  # and it prints nothing


def test_self_check_lists_unanswered_checks(settings):
    with FakePrinter() as fake:
        fake.status[3] = None  # no reply to the error-cause request
        tcp = replace(settings, printer_mode="tcp", printer_host="127.0.0.1", printer_port=fake.port,
                      printer_timeout=2)
        with TestClient(create_app(tcp)) as client:
            body = client.get("/api/v1/printer/self-check").json()
    assert "cutter" in body["unanswered"]
    assert "cover" not in body["unanswered"]


def test_self_check_when_printer_is_off(settings):
    fake = FakePrinter().start()
    port = fake.port
    fake.stop()
    tcp = replace(settings, printer_mode="tcp", printer_host="127.0.0.1", printer_port=port, printer_timeout=1)
    with TestClient(create_app(tcp)) as client:
        body = client.get("/api/v1/printer/self-check").json()
    assert body["reachable"] is False
    assert "cannot reach printer" in body["error"]


def test_metrics_count_printed_tickets(settings):
    with TestClient(create_app(settings)) as client:
        client.post("/api/v1/tickets", json={"recipient": "yannic", "message": "hi"})
        client.post("/api/v1/tickets", json={"recipient": "wife", "message": "hello"})
        app = client.app
        app.state.scheduler.run_once()
        counters = client.get("/api/v1/metrics").json()["counters"]
    assert counters["tickets_printed"] == 2


def test_metrics_count_failures_and_dead_letters(settings):
    with FakePrinter() as fake:
        port = fake.port
    # The printer is off, so every attempt fails and the single allowed attempt dead-letters.
    tcp = replace(settings, printer_mode="tcp", printer_host="127.0.0.1", printer_port=port,
                  printer_timeout=1, max_attempts=1)
    app = create_app(tcp)
    with TestClient(app) as client:
        client.post("/api/v1/tickets", json={"recipient": "yannic", "message": "hi"})
        app.state.scheduler.run_once()
        body = client.get("/api/v1/metrics").json()
    assert body["counters"]["print_failures"] == 1
    assert body["counters"]["tickets_dead_lettered"] == 1
    assert "tickets_printed" not in body["counters"]
    assert body["queue_paused"] is None
