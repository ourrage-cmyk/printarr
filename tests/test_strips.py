import dataclasses

from fastapi.testclient import TestClient

from app.main import create_app
from app.printer import PrinterError
from app.store import TicketStore


class Recorder:
    def __init__(self, fail=False):
        self.payloads = []
        self.fail = fail

    def send(self, data):
        if self.fail:
            raise PrinterError("printer is off")
        self.payloads.append(data)

    def read_status(self):
        return {}


def make(settings, transport=None, **changes):
    settings = dataclasses.replace(settings, scheduler_enabled=False, **changes)
    transport = transport or Recorder()
    return create_app(settings, transport=transport), transport


def queue(client, recipient, text, **extra):
    return client.post("/api/v1/tickets", json={"recipient": recipient, "message": text, **extra}).json()


def test_on_release_tickets_wait_in_the_pile_and_never_print_alone(settings):
    app, transport = make(settings)
    with TestClient(app) as client:
        ticket = queue(client, "yannic", "later", delivery="on_release")
        assert ticket["status"] == "held" and ticket["delivery"] == "on_release"
        assert app.state.scheduler.run_once() == 0
        assert transport.payloads == []


def test_release_prints_only_that_persons_pile_as_one_strip(settings):
    app, transport = make(settings)
    with TestClient(app) as client:
        mine = queue(client, "yannic", "for me", delivery="on_release")
        hers = queue(client, "wife", "for her", delivery="on_release")
        result = client.post("/api/v1/people/yannic/release", json={"trigger": "morning"}).json()
        assert [s["ticket_ids"] for s in result["strips"]] == [[mine["id"]]]
        assert len(transport.payloads) == 1
        assert client.get(f"/api/v1/tickets/{hers['id']}").json()["status"] == "held"
        stored = TicketStore(settings.db_path).get(mine["id"])
        assert stored["status"] == "sent" and stored["strip_trigger"] == "morning"
        assert stored["strip_id"] == result["strips"][0]["strip_id"]


def test_a_repeat_release_prints_nothing_new(settings):
    app, transport = make(settings)
    with TestClient(app) as client:
        queue(client, "wife", "once", delivery="on_release")
        client.post("/api/v1/people/wife/release", json={"trigger": "evening"})
        again = client.post("/api/v1/people/wife/release", json={"trigger": "evening"}).json()
        assert again["strips"] == []
        assert len(transport.payloads) == 1


def test_a_strip_is_cut_after_max_blocks(settings):
    app, transport = make(settings, strip_max_blocks=3)
    with TestClient(app) as client:
        for i in range(7):
            queue(client, "yannic", f"note {i}", delivery="on_release")
        result = client.post("/api/v1/people/yannic/release", json={}).json()
        assert [len(s["ticket_ids"]) for s in result["strips"]] == [3, 3, 1]
        assert len(transport.payloads) == 3


def test_a_failed_print_keeps_the_pile_held(settings):
    app, transport = make(settings, transport=Recorder(fail=True))
    with TestClient(app) as client:
        ticket = queue(client, "yannic", "keep me", delivery="on_release")
        response = client.post("/api/v1/people/yannic/release", json={"trigger": "arrival"})
        assert response.status_code == 502
        assert client.get(f"/api/v1/tickets/{ticket['id']}").json()["status"] == "held"


def test_delivery_rules(settings):
    app, _ = make(settings)
    with TestClient(app) as client:
        assert queue(client, "wife", "x", delivery="at").get("detail")  # needs send_at
        assert client.post(
            "/api/v1/tickets",
            json={"recipient": "wife", "message": "x", "delivery": "now", "send_at": "2026-10-26T15:00:00"},
        ).status_code == 422
        assert client.post(
            "/api/v1/tickets",
            json={"recipient": "wife", "message": "x", "delivery": "on_release", "send_at": "2026-10-26T15:00:00"},
        ).status_code == 422
        at = client.post(
            "/api/v1/tickets",
            json={"recipient": "wife", "message": "x", "delivery": "at", "send_at": "2026-10-26T15:00:00"},
        ).json()
        assert at["delivery"] == "at" and at["status"] == "pending"


def test_slot_tickets_can_wait_for_release(settings):
    app, _ = make(settings)
    with TestClient(app) as client:
        ticket = client.post(
            "/api/v1/tickets/slots",
            json={"template": 102, "recipient": "wife", "slots": {"paragraph": "Hello"}, "delivery": "on_release"},
        ).json()
        assert ticket["status"] == "held" and ticket["delivery"] == "on_release"


def test_the_strip_has_blank_margins_at_top_and_bottom(settings):
    app, transport = make(settings, strip_margin_dots=90)
    with TestClient(app) as client:
        queue(client, "yannic", "hi", delivery="on_release")
        client.post("/api/v1/people/yannic/release", json={})
    assert len(transport.payloads) == 1
    assert transport.payloads[0].count(b"\x00" * 64 * 90) >= 2  # top and bottom margins
