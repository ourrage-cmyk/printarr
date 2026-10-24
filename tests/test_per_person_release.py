"""Each person's pile is assembled at their release, and Home Assistant is read when the ticket prints.

Yannic and Allyson each queue held tickets. Releasing one person prints only that person's pile, in either
order, and a repeat release prints nothing. Briefings that use Home Assistant read it at print time, so a
value that changed after the ticket was queued prints as it is at release.
"""

import dataclasses

from fastapi.testclient import TestClient

from app.ha import HAClient, HAError
from app.main import create_app
from app.store import TicketStore
from tests.test_strips import Recorder

DAY = "2026-10-26"


class FakeHA:
    """Stands in for Home Assistant. Records every read, so a test can tell queue time from print time."""

    def __init__(self) -> None:
        self.states = {"sensor.body_battery": "71", "sensor.steps": "4200"}
        self.history = {"sensor.steps": [100.0, 200.0, 300.0]}
        self.reads: list[str] = []

    def state(self, entity_id: str) -> str:
        self.reads.append(f"state {entity_id}")
        return self.states[entity_id]

    def numeric_history(self, entity_id: str, hours: int) -> list[float]:
        self.reads.append(f"history {entity_id}")
        return list(self.history.get(entity_id, []))


def setup_ha(monkeypatch) -> FakeHA:
    fake = FakeHA()
    monkeypatch.setattr(HAClient, "state", lambda self, entity_id: fake.state(entity_id))
    monkeypatch.setattr(HAClient, "numeric_history", lambda self, entity_id, hours: fake.numeric_history(entity_id, hours))
    return fake


def set_ha(store_path: str) -> None:
    store = TicketStore(store_path)
    store.set_setting("ha_url", "http://ha.test")
    store.set_setting("ha_token", "test-token")


def make(settings, tmp_path, name="db"):
    folder = tmp_path / name
    folder.mkdir()
    settings = dataclasses.replace(
        settings, scheduler_enabled=False, db_path=str(folder / "printarr.db"), output_dir=str(folder / "out")
    )
    transport = Recorder()
    return create_app(settings, transport=transport), transport, settings.db_path


def queue_mixed(client: TestClient) -> dict[str, set[str]]:
    """Two briefings and two messages per person, all held for release. Returns each person's ticket ids."""
    ids: dict[str, set[str]] = {"yannic": set(), "wife": set()}
    for person in ("yannic", "wife"):
        briefing = client.post("/api/v1/tickets/slots", json={
            "template": 101, "recipient": person, "sender": "home-assistant", "kind": "morning",
            "tone": "neutral", "slots": {"title": "Morning"}, "delivery": "on_release",
            "idempotency_key": f"morning:{person}:{DAY}",
        })
        assert briefing.status_code == 201, briefing.text
        ids[person].add(briefing.json()["id"])
    for sender, person, text in (
        ("wife", "yannic", "Bins are out"),
        ("yannic", "wife", "Back by seven"),
        ("wife", "yannic", "Call the plumber"),
        ("yannic", "wife", "Dinner is in the oven"),
    ):
        message = client.post("/api/v1/tickets", json={
            "kind": "note", "tone": "neutral", "from_user": sender, "to_user": person, "recipient": person,
            "message": text, "sender": sender, "delivery": "on_release",
        })
        assert message.status_code == 201, message.text
        ids[person].add(message.json()["id"])
    return ids


def printed_ids(result: dict) -> set[str]:
    return {ticket_id for strip in result["strips"] for ticket_id in strip["ticket_ids"]}


def release(client: TestClient, person: str) -> dict:
    response = client.post(f"/api/v1/people/{person}/release", json={"trigger": "morning"})
    assert response.status_code == 200, response.text
    return response.json()


def test_each_release_prints_only_that_persons_pile_in_either_order(settings, tmp_path):
    for order in (("yannic", "wife"), ("wife", "yannic")):
        app, transport, _ = make(settings, tmp_path, name="-".join(order))
        with TestClient(app) as client:
            ids = queue_mixed(client)
            first, second = order

            done = release(client, first)
            assert printed_ids(done) == ids[first], f"{first} released another person's tickets"
            assert len(done["strips"]) == 1, "one release prints one strip"
            assert all(client.get(f"/api/v1/tickets/{t}").json()["status"] == "sent" for t in ids[first])
            assert all(client.get(f"/api/v1/tickets/{t}").json()["status"] == "held" for t in ids[second])

            again = release(client, first)
            assert again["strips"] == [], "a repeat release prints nothing new"

            later = release(client, second)
            assert printed_ids(later) == ids[second]
            assert len(transport.payloads) == 2


def test_home_assistant_is_read_when_a_briefing_prints_not_when_it_is_queued(settings, tmp_path, monkeypatch):
    fake = setup_ha(monkeypatch)
    app, transport, db_path = make(settings, tmp_path)
    with TestClient(app) as client:
        set_ha(db_path)
        queued = client.post("/api/v1/tickets/slots", json={
            "template": 101, "recipient": "yannic", "sender": "home-assistant", "kind": "morning",
            "tone": "neutral", "slots": {"title": "Morning", "metrics": [
                {"label": "STEPS", "entity_id": "sensor.steps", "unit": ""},
            ]}, "delivery": "on_release",
        })
        assert queued.status_code == 201, queued.text
        assert fake.reads == [], "nothing is read from Home Assistant while the ticket waits"

        fake.states["sensor.steps"] = "9999"
        release(client, "yannic")
        assert "state sensor.steps" in fake.reads, "the value is read at release"


def test_a_briefing_preset_reads_its_graph_at_print_time(settings, tmp_path, monkeypatch):
    fake = setup_ha(monkeypatch)
    app, transport, db_path = make(settings, tmp_path)
    with TestClient(app) as client:
        set_ha(db_path)
        preset = {
            "time_of_day": "morning",
            "metrics": [
                {"label": "STEPS", "entity_id": "sensor.steps"},
                {"label": "BATTERY", "entity_id": "sensor.body_battery", "unit": "%"},
                {"label": "SLEEP", "value": 7.5, "unit": "h"},
            ],
            "graph": {"title": "STEPS", "entity_id": "sensor.steps", "hours": 24},
            "body": "Quiet morning.",
            "fun_fact": "Honey never spoils.",
        }
        queued = client.post("/api/v1/tickets/compose", json={
            "preset": "briefing", "slots": preset, "recipient": "yannic", "sender": "home-assistant",
            "delivery": "on_release",
        })
        assert queued.status_code == 201, queued.text
        assert "history sensor.steps" not in fake.reads, "the graph is not read while the ticket waits"
        stored = TicketStore(db_path).get(queued.json()["id"])
        assert '"series"' not in (stored.get("slots_json") or ""), "queued values must not be frozen on the ticket"

        fake.history["sensor.steps"] = [5.0, 6.0, 7.0, 8.0]
        release(client, "yannic")
        assert "history sensor.steps" in fake.reads, "the graph is read at release"


def test_an_unreachable_home_assistant_never_blocks_a_queued_ticket(settings, tmp_path, monkeypatch):
    fake = setup_ha(monkeypatch)

    def down(entity_id: str) -> str:
        raise HAError("Home Assistant unreachable")

    monkeypatch.setattr(fake, "state", down)
    app, transport, db_path = make(settings, tmp_path)
    with TestClient(app) as client:
        set_ha(db_path)
        queued = client.post("/api/v1/tickets", json={
            "kind": "note", "tone": "neutral", "recipient": "yannic", "sender": "home-assistant",
            "message": "Steps check", "delivery": "on_release",
            "blocks": [{"type": "value", "entity_id": "sensor.steps", "label": "STEPS"}],
        })
        assert queued.status_code == 201, queued.text
        assert queued.json()["status"] == "held"

        result = release(client, "yannic")
        assert printed_ids(result) == {queued.json()["id"]}, "the ticket prints even though Home Assistant is down"
        assert len(transport.payloads) == 1
