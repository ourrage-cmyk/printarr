from dataclasses import replace

import pytest

from app.printer import PrinterError
from app.scheduler import Scheduler
from app.store import TicketNotFound, TicketStateError, TicketStore


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


def test_interrupted_tickets_are_requeued(store):
    ticket = create(store)
    store.claim_due(10, 10)
    assert store.get(ticket["id"])["status"] == "printing"

    assert store.recover_interrupted(20) == 1
    assert store.get(ticket["id"])["status"] == "pending"


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
