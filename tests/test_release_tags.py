"""A release prints the tickets tagged for it, and builds the default briefing when none was queued.

A briefing queued for the morning waits for the morning release and is not printed at an evening arrival.
A morning or evening release with no briefing for it prints the default briefing (its values read from Home
Assistant at print time), once a day. A request prints the whole pile. Every ticket on a printed strip keeps
its image, so GET /tickets/{id}/image works for each one.
"""

from fastapi.testclient import TestClient

from tests.test_per_person_release import make, set_ha, setup_ha

DAY = "2026-10-26"
METRICS = [
    {"label": "Steps", "entity_id": "sensor.steps"},
    {"label": "Battery", "entity_id": "sensor.body_battery"},
    {"label": "Water", "value": "3", "unit": "L"},
]
GRAPH = {"title": "Steps", "entity_id": "sensor.steps"}


def briefing(client: TestClient, person: str, time_of_day: str, key: str | None = None) -> str:
    body = {
        "preset": "briefing", "recipient": person, "sender": "hermes", "delivery": "on_release",
        "slots": {"time_of_day": time_of_day, "metrics": METRICS, "graph": GRAPH,
                  "body": "Rain after lunch.", "fun_fact": "Octopuses have three hearts."},
    }
    if key:
        body["idempotency_key"] = key
    response = client.post("/api/v1/tickets/compose", json=body)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def release(client: TestClient, person: str, trigger: str) -> dict:
    response = client.post(f"/api/v1/people/{person}/release", json={"trigger": trigger})
    assert response.status_code == 200, response.text
    return response.json()


def printed(result: dict) -> set[str]:
    return {ticket_id for strip in result["strips"] for ticket_id in strip["ticket_ids"]}


def set_default(client: TestClient) -> None:
    response = client.put("/api/v1/briefing/default", json={"metrics": METRICS, "graph": GRAPH})
    assert response.status_code == 200, response.text


def test_morning_briefing_waits_for_the_morning_release_not_an_evening_arrival(settings, tmp_path):
    app, transport, _ = make(settings, tmp_path)
    with TestClient(app) as client:
        morning = briefing(client, "yannic", "morning")
        assert client.get(f"/api/v1/tickets/{morning}").json()["release_on"] == "morning"

        early = release(client, "yannic", "arrival")
        assert printed(early) == set(), "an evening arrival must not print the morning briefing"
        assert client.get(f"/api/v1/tickets/{morning}").json()["status"] == "held"

        done = release(client, "yannic", "morning")
        assert printed(done) == {morning}


def test_evening_briefing_is_tagged_evening_and_a_request_prints_everything(settings, tmp_path):
    app, _, _ = make(settings, tmp_path)
    with TestClient(app) as client:
        evening = briefing(client, "wife", "evening")
        assert client.get(f"/api/v1/tickets/{evening}").json()["release_on"] == "evening"
        message = client.post("/api/v1/tickets", json={
            "kind": "note", "recipient": "wife", "message": "Bins are out", "sender": "yannic",
            "delivery": "on_release", "release_on": "morning",
        })
        assert message.status_code == 201, message.text
        morning_note = message.json()["id"]

        assert printed(release(client, "wife", "morning")) == {morning_note}
        assert printed(release(client, "wife", "request")) == {evening}


def test_default_briefing_prints_at_a_morning_release_with_nothing_queued(settings, tmp_path, monkeypatch):
    fake = setup_ha(monkeypatch)
    app, transport, db_path = make(settings, tmp_path)
    with TestClient(app) as client:
        set_ha(db_path)
        set_default(client)
        assert client.get("/api/v1/briefing/default").json()["graph"]["entity_id"] == "sensor.steps"

        done = release(client, "yannic", "morning")
        assert len(done["strips"]) == 1
        ticket_id = done["strips"][0]["ticket_ids"][0]
        ticket = client.get(f"/api/v1/tickets/{ticket_id}").json()
        assert ticket["kind"] == "morning"
        assert ticket["status"] == "sent"
        assert "state sensor.steps" in fake.reads, "Home Assistant is read when the default briefing prints"

        again = release(client, "yannic", "morning")
        assert again["strips"] == [], "a second morning release the same day builds and prints nothing new"


def test_no_default_briefing_when_one_is_queued_for_that_release(settings, tmp_path, monkeypatch):
    setup_ha(monkeypatch)
    app, _, _ = make(settings, tmp_path)
    with TestClient(app) as client:
        set_default(client)
        queued = briefing(client, "yannic", "morning", key=f"morning:yannic:{DAY}")
        done = release(client, "yannic", "morning")
        assert printed(done) == {queued}
        assert len(done["strips"]) == 1, "the queued briefing prints alone, with no default added"


def test_no_default_briefing_is_built_until_one_is_set(settings, tmp_path):
    app, _, _ = make(settings, tmp_path)
    with TestClient(app) as client:
        assert client.get("/api/v1/briefing/default").status_code == 404
        assert release(client, "yannic", "evening")["strips"] == []

        set_default(client)
        assert client.delete("/api/v1/briefing/default").status_code == 200
        assert release(client, "yannic", "evening")["strips"] == []


def test_every_ticket_on_a_printed_strip_has_the_strip_image(settings, tmp_path):
    app, transport, _ = make(settings, tmp_path)
    with TestClient(app) as client:
        ids = [
            client.post("/api/v1/tickets", json={
                "kind": "note", "recipient": "yannic", "message": f"Note {n}", "sender": "wife",
                "delivery": "on_release",
            }).json()["id"]
            for n in range(3)
        ]
        done = release(client, "yannic", "request")
        assert printed(done) == set(ids)
        for ticket_id in ids:
            image = client.get(f"/api/v1/tickets/{ticket_id}/image")
            assert image.status_code == 200, f"{ticket_id} has no image"
            assert image.headers["content-type"] == "image/png"
