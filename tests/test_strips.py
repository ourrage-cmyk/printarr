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


def test_a_pile_ticket_cannot_be_released_alone(settings):
    app, transport = make(settings)
    with TestClient(app) as client:
        ticket = queue(client, "wife", "in the pile", delivery="on_release")
        refused = client.post(f"/api/v1/tickets/{ticket['id']}/release")
        assert refused.status_code == 409
        assert app.state.scheduler.run_once() == 0
        assert transport.payloads == []


def test_a_hold_key_release_leaves_the_pile_alone(settings):
    app, transport = make(settings)
    with TestClient(app) as client:
        queue(client, "wife", "in the pile", delivery="on_release", hold=True, hold_key="user-home")
        assert client.post("/api/v1/holds/user-home/release").json() == []
        assert app.state.scheduler.run_once() == 0
        strips = client.post("/api/v1/people/wife/release", json={}).json()["strips"]
        assert len(strips) == 1 and transport.payloads


def test_a_retried_pile_ticket_goes_back_to_its_pile(settings):
    app, transport = make(settings)
    with TestClient(app) as client:
        ticket = queue(client, "wife", "retry me", delivery="on_release")
        store = app.state.scheduler.store
        store.claim([ticket["id"]])
        store.record_failure(ticket["id"], "printer off", retry_at_ms=None)
        retried = client.post(f"/api/v1/tickets/{ticket['id']}/retry").json()
        assert retried["status"] == "held" and retried["delivery"] == "on_release"
        assert app.state.scheduler.run_once() == 0
        assert transport.payloads == []


class FailAfter(Recorder):
    """Prints the first `ok` jobs, then the printer goes off."""

    def __init__(self, ok):
        super().__init__()
        self.ok = ok

    def send(self, data):
        if len(self.payloads) >= self.ok:
            raise PrinterError("printer went off")
        super().send(data)


def test_a_release_that_fails_part_way_reports_the_strips_already_printed(settings):
    app, transport = make(settings, FailAfter(ok=1), strip_max_blocks=2)
    with TestClient(app) as client:
        for i in range(4):
            queue(client, "wife", f"note {i}", delivery="on_release")
        response = client.post("/api/v1/people/wife/release", json={"trigger": "evening"})
        assert response.status_code == 502
        detail = response.json()["detail"]
        assert len(detail["strips"]) == 1 and len(detail["strips"][0]["ticket_ids"]) == 2
        assert "printed 1 strip(s)" in detail["message"]
        # the printed strip is recorded, the rest of the pile is still waiting
        assert len(app.state.scheduler.store.pile("wife")) == 2


def test_a_database_hiccup_after_printing_does_not_strand_the_ticket(settings, monkeypatch):
    app, transport = make(settings)
    with TestClient(app) as client:
        ticket = queue(client, "yannic", "printed once")
        store = app.state.scheduler.store
        real = store.mark_sent
        calls = {"n": 0}

        def flaky(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("database is locked")
            return real(*args, **kwargs)

        monkeypatch.setattr(store, "mark_sent", flaky)
        monkeypatch.setattr("app.scheduler.MARK_SENT_RETRY_S", 0)
        assert app.state.scheduler.run_once() == 1
        assert store.get(ticket["id"])["status"] == "sent"
        assert len(transport.payloads) == 1


def test_a_composed_greeting_starts_a_new_strip_in_the_pile(settings):
    import json

    from app.scheduler import opens_strip

    briefing = {"template_id": 101, "slots_json": "{}"}
    composed = {"template_id": 103, "slots_json": json.dumps({"blocks": [{"type": "greeting"}]})}
    note = {"template_id": 102, "slots_json": "{}"}
    tip = {"template_id": 103, "slots_json": json.dumps({"blocks": [{"type": "tip"}]})}
    assert opens_strip(briefing) and opens_strip(composed)
    assert not opens_strip(note) and not opens_strip(tip)


def test_tickets_printed_together_lose_the_cut_margins_between_them():
    from app.receipt import Line
    from app.scheduler import INNER_GAP

    def part(top, body, bottom):
        data = bytes(64 * top) + b"\xff" * (64 * body) + bytes(64 * bottom)
        return [Line("", raster=(64, top + body + bottom, data))]

    from app.scheduler import Scheduler

    parts = [part(24, 100, 66), part(24, 50, 66), part(24, 30, 66)]
    lines = Scheduler._strip_lines(type("S", (), {"settings": type("C", (), {"strip_margin_dots": 0})()})(), parts)
    total = sum(line.raster[1] for line in lines)
    assert total == 24 + 100 + INNER_GAP + 50 + INNER_GAP + 30 + 66  # the top of the first and the bottom of the last stay


def test_a_tall_picture_is_sent_in_bands_a_printer_can_take():
    from app.escpos import encode
    from app.receipt import Line

    data = b"\xff" * (64 * 1120)
    stream = encode([Line("", raster=(64, 1120, data))])
    assert stream.count(b"\x1d(L\x02\x000\x32") == 2  # two prints, each under 65535 bytes


def test_one_release_is_one_piece_whatever_the_greetings():
    from app.scheduler import Scheduler

    def ticket(i, template_id=7):
        return {"id": str(i), "template_id": template_id, "slots_json": "{}"}

    sched = Scheduler.__new__(Scheduler)
    sched.settings = type("S", (), {"strip_max_blocks": 12})()
    pile = [ticket("a", 102), ticket("b", 102), ticket("brief", 101), ticket("c", 101), ticket("d", 102)]
    assert [len(chunk) for chunk in sched._strip_chunks(pile)] == [5]


def test_every_ticket_in_a_piece_recalls_the_whole_piece(settings):
    app, transport = make(settings)
    with TestClient(app) as client:
        a = queue(client, "yannic", "first note", delivery="on_release")
        b = queue(client, "yannic", "second note", delivery="on_release")
        client.post("/api/v1/people/yannic/release", json={"trigger": "morning"})
        one = client.get(f"/api/v1/tickets/{a['id']}/image")
        two = client.get(f"/api/v1/tickets/{b['id']}/image")
        assert one.status_code == two.status_code == 200
        assert one.content == two.content
        alone = queue(client, "yannic", "first note", delivery="now")
        app.state.scheduler.run_once()
        single = client.get(f"/api/v1/tickets/{alone['id']}/image").content
        assert len(one.content) > len(single)  # the piece holds both notes

def test_the_cut_space_carries_print_time_and_code_that_the_api_resolves(settings):
    app, transport = make(settings)
    with TestClient(app) as client:
        a = queue(client, "yannic", "first note", delivery="on_release")
        b = queue(client, "yannic", "second note", delivery="on_release")
        result = client.post("/api/v1/people/yannic/release", json={"trigger": "morning"}).json()
        code = result["strips"][0]["strip_id"][:6]
        assert f"  {code}".encode() in transport.payloads[0]
        found = client.get(f"/api/v1/prints/{code}").json()
        assert found["print_code"] == code and found["printed_at"]
        assert [t["id"] for t in found["tickets"]] == [a["id"], b["id"]]
        assert client.get(f"/api/v1/tickets/{a['id']}").json()["print_code"] == code
        assert client.get("/api/v1/prints/zzzz").status_code == 422
        assert client.get("/api/v1/prints/ffffff").status_code == 404
        alone = queue(client, "yannic", "solo", delivery="now")
        app.state.scheduler.run_once()
        solo = alone["id"][:6]
        assert f"  {solo}".encode() in transport.payloads[-1]
        assert client.get(f"/api/v1/prints/{solo}").json()["tickets"][0]["id"] == alone["id"]
