"""TCP transport and scheduler against the fake printer socket, including fault injection."""

import time
from dataclasses import replace

import pytest

from app.printer import PrinterError, PrintInterrupted, UnbuiltTransport, build_transport
from app.scheduler import Scheduler
from app.store import TicketStore
from tests.fake_printer import FakePrinter


def wait_until(predicate, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("timed out waiting for the fake printer")
        time.sleep(0.01)


@pytest.fixture
def printer():
    with FakePrinter() as fake:
        yield fake


@pytest.fixture
def store(settings):
    s = TicketStore(settings.db_path)
    s.init()
    return s


def test_large_job_arrives_intact_in_chunks(printer):
    payload = bytes(range(256)) * 1024  # 256 KB, many chunks
    printer.transport().send(payload)
    wait_until(lambda: len(printer.jobs) == 1)
    assert printer.jobs[0] == payload


def test_status_answers_are_read_for_each_request(printer):
    printer.status = {1: 0x12, 2: 0x12 | 0x04, 3: 0x12, 4: 0x12 | 0x60}
    assert printer.transport().read_status() == printer.status


def test_unanswered_status_request_is_none(printer):
    printer.status[3] = None
    answers = printer.transport().read_status()
    assert answers[3] is None
    assert answers[1] == 0x12 and answers[2] == 0x12 and answers[4] == 0x12


def test_unreachable_printer_is_a_printer_error(printer):
    printer.stop()
    with pytest.raises(PrinterError) as info:
        printer.transport().send(b"hello")
    assert not isinstance(info.value, PrintInterrupted)
    assert "cannot reach printer" in str(info.value)


def test_connection_dropped_mid_job_reports_how_much_was_sent(printer):
    printer.drop_job_after = 1024
    payload = b"\x55" * (16 * 1024 * 1024)  # far more than the socket buffers can hold
    with pytest.raises(PrintInterrupted) as info:
        printer.transport().send(payload)
    assert 0 <= info.value.bytes_sent < len(payload)
    wait_until(lambda: len(printer.partial_jobs) == 1)
    assert printer.jobs == []  # the printer never saw a complete job


def test_power_cycle_retries_the_ticket_once_printer_is_back(printer, store, settings):
    ticket = store.create(recipient="yannic", message="hi", send_at_ms=0, template_id=1,
                          decorations=(), selection="rule")
    now = [0]
    scheduler = Scheduler(store, printer.transport(), settings, clock=lambda: now[0])

    printer.stop()  # power off
    assert scheduler.run_once() == 1
    assert store.get(ticket["id"])["status"] == "pending"
    assert store.get(ticket["id"])["attempts"] == 1

    printer.start()  # power on again, on the same port
    now[0] = 31_000  # after the 30 s backoff
    assert scheduler.run_once() == 1
    assert store.get(ticket["id"])["status"] == "sent"
    wait_until(lambda: len(printer.jobs) == 1)


def test_cover_fault_seen_over_the_socket_pauses_then_resumes(printer, store, settings):
    store.create(recipient="yannic", message="hi", send_at_ms=0, template_id=1,
                 decorations=(), selection="rule")
    now = [0]
    scheduler = Scheduler(store, printer.transport(), settings, clock=lambda: now[0])
    printer.status[2] = 0x12 | 0x04  # cover open

    assert scheduler.run_once() == 0
    assert "printer cover open" in scheduler.paused_reason
    assert printer.jobs == []

    printer.status[2] = 0x12
    now[0] = 6_000
    assert scheduler.run_once() == 1
    wait_until(lambda: len(printer.jobs) == 1)


def test_usb_and_serial_are_placeholders_that_report_unreachable(settings):
    for mode in ("usb", "serial"):
        transport = build_transport(replace(settings, printer_mode=mode))
        assert isinstance(transport, UnbuiltTransport)
        with pytest.raises(PrinterError, match="not built yet"):
            transport.check()
