from dataclasses import replace

import pytest

from app.printer import PrinterError
from app.scheduler import Scheduler
from app.store import TicketNotFound, TicketStateError, TicketStore, now_ms


class RecordingTransport:
    target = "fake"

    def __init__(self, fail: int = 0) -> None:
        self.fail = fail
        self.sent: list[bytes] = []

    def send(self, data: bytes) -> None:
        if self.fail:
            self.fail -= 1
            raise PrinterError("offline")
        self.sent.append(data)

    def check(self) -> None:
        pass

    def read_status(self) -> dict[int, int | None]:
        return {1: 0x12, 2: 0x12, 3: 0x12, 4: 0x12}


class FaultyTransport(RecordingTransport):
    """Reports a fault until `clear()` is called, the way a cover left open does."""

    def __init__(self, fault_bytes: dict[int, int]) -> None:
        super().__init__()
        self.fault_bytes = fault_bytes
        self.status_reads = 0

    def read_status(self) -> dict[int, int | None]:
        self.status_reads += 1
        answers = {1: 0x12, 2: 0x12, 3: 0x12, 4: 0x12}
        answers.update(self.fault_bytes)
        return answers

    def clear(self) -> None:
        self.fault_bytes = {}


class UnreachableTransport(RecordingTransport):
    def send(self, data: bytes) -> None:
        raise PrinterError("cannot reach printer")

    def read_status(self) -> dict[int, int | None]:
        raise PrinterError("cannot reach printer")


@pytest.fixture
def store(settings):
    s = TicketStore(settings.db_path)
    s.init()
    return s


def create(store, send_at_ms=0):
    return store.create(
        recipient="yannic", message="hi", send_at_ms=send_at_ms,
        template_id=1, decorations=(), selection="rule",
    )


def test_due_ticket_prints_once(store, settings):
    ticket = create(store, send_at_ms=1_000)
    transport = RecordingTransport()
    scheduler = Scheduler(store, transport, settings, clock=lambda: 2_000)

    assert scheduler.run_once() == 1
    assert scheduler.run_once() == 0

    done = store.get(ticket["id"])
    assert done["status"] == "sent"
    assert done["attempts"] == 1
    assert done["printed_at"] is not None
    assert len(transport.sent) == 1


def test_future_ticket_waits(store, settings):
    ticket = create(store, send_at_ms=10_000)
    scheduler = Scheduler(store, RecordingTransport(), settings, clock=lambda: 5_000)

    assert scheduler.run_once() == 0
    assert store.get(ticket["id"])["status"] == "pending"


def test_failed_print_is_retried_with_backoff(store, settings):
    settings = replace(settings, max_attempts=2, retry_base_seconds=10)
    ticket = create(store)
    clock = {"now": 1_000}
    scheduler = Scheduler(store, RecordingTransport(fail=1), settings, clock=lambda: clock["now"])

    scheduler.run_once()
    after_failure = store.get(ticket["id"])
    assert after_failure["status"] == "pending"
    assert after_failure["last_error"] == "offline"

    assert scheduler.run_once() == 0  # still inside the 10 s backoff

    clock["now"] = 11_001
    scheduler.run_once()
    assert store.get(ticket["id"])["status"] == "sent"


def test_gives_up_after_max_attempts(store, settings):
    settings = replace(settings, max_attempts=2, retry_base_seconds=1)
    ticket = create(store)
    clock = {"now": 1_000}
    scheduler = Scheduler(store, RecordingTransport(fail=5), settings, clock=lambda: clock["now"])

    scheduler.run_once()
    clock["now"] = 3_000
    scheduler.run_once()

    failed = store.get(ticket["id"])
    assert failed["status"] == "failed"
    assert failed["attempts"] == 2


def test_cancel_then_retry(store):
    ticket = create(store)
    assert store.cancel(ticket["id"])["status"] == "cancelled"
    with pytest.raises(TicketStateError):
        store.cancel(ticket["id"])
    assert store.requeue(ticket["id"])["status"] == "pending"


def test_unknown_ticket_raises(store):
    with pytest.raises(TicketNotFound):
        store.cancel("missing")


def test_interrupted_tickets_fail_instead_of_reprinting(store, settings):
    ticket = create(store)
    store.claim_due(10, 10)
    assert store.get(ticket["id"])["status"] == "printing"

    assert store.fail_interrupted(20) == [ticket["id"]]
    failed = store.get(ticket["id"])
    assert failed["status"] == "failed"
    assert "not reprinted" in failed["last_error"]

    transport = RecordingTransport()
    assert Scheduler(store, transport, settings, clock=lambda: 30).run_once() == 0
    assert transport.sent == []


def test_requeue_prints_an_interrupted_ticket_on_purpose(store, settings):
    ticket = create(store)
    store.claim_due(10, 10)
    store.fail_interrupted(20)
    store.requeue(ticket["id"])

    transport = RecordingTransport()
    assert Scheduler(store, transport, settings, clock=now_ms).run_once() == 1
    assert store.get(ticket["id"])["status"] == "sent"


def test_same_idempotency_key_returns_the_first_ticket(store):
    first = store.create(
        recipient="yannic", message="Morning", send_at_ms=0, template_id=1,
        decorations=(), selection="rule", idempotency_key="morning:yannic:2026-10-26",
    )
    second = store.create(
        recipient="yannic", message="Morning again", send_at_ms=0, template_id=1,
        decorations=(), selection="rule", idempotency_key="morning:yannic:2026-10-26",
    )
    assert second["id"] == first["id"]
    assert second["message"] == "Morning"
    assert len(store.search(recipient="yannic")) == 1


def test_tickets_without_a_key_are_not_merged(store):
    a = create(store)
    b = create(store)
    assert a["id"] != b["id"]


def test_release_hold_twice_is_harmless(store):
    store.create(
        recipient="yannic", message="Home", send_at_ms=0, template_id=1,
        decorations=(), selection="rule", held=True, hold_key="user-home",
    )
    assert len(store.release_hold("user-home")) == 1
    assert store.release_hold("user-home") == []


def test_queue_pauses_while_cover_is_open_and_resumes_when_closed(store, settings):
    ticket = create(store, send_at_ms=0)
    now = [0]
    transport = FaultyTransport({2: 0x12 | 0x04})  # cover open
    scheduler = Scheduler(store, transport, settings, clock=lambda: now[0])

    assert scheduler.run_once() == 0
    assert "printer cover open" in scheduler.paused_reason
    assert store.get(ticket["id"])["status"] == "pending"
    assert store.get(ticket["id"])["attempts"] == 0  # a fault does not use up an attempt

    transport.clear()
    now[0] = 6_000  # the next status poll, after poll_interval (5 s)
    assert scheduler.run_once() == 1
    assert scheduler.paused_reason is None
    assert store.get(ticket["id"])["status"] == "sent"


def test_status_is_read_once_per_poll_interval(store, settings):
    create(store, send_at_ms=0)
    transport = FaultyTransport({3: 0x12 | 0x08})  # autocutter error
    scheduler = Scheduler(store, transport, settings, clock=lambda: 0)
    for at_ms in (0, 1_000, 2_000, 4_999):
        scheduler.clock = lambda at_ms=at_ms: at_ms
        scheduler.run_once()
    assert transport.status_reads == 1


def test_paper_near_end_does_not_pause(store, settings):
    create(store, send_at_ms=0)
    transport = FaultyTransport({4: 0x12 | 0x0C})
    assert Scheduler(store, transport, settings, clock=lambda: 0).run_once() == 1


def test_unreachable_printer_backs_off_instead_of_pausing(store, settings):
    ticket = create(store, send_at_ms=0)
    scheduler = Scheduler(store, UnreachableTransport(), settings, clock=lambda: 0)
    assert scheduler.run_once() == 1
    after = store.get(ticket["id"])
    assert after["status"] == "pending"
    assert after["attempts"] == 1
    assert after["next_attempt_at"] is not None
    assert scheduler.paused_reason is None
