from dataclasses import replace
from pathlib import Path

from app.escpos import encode
from app.ha import HAError
from app.render.canvas import PAPER_DOTS
from app.render import system
from app.render.designs import SAMPLE_MORNING, morning_system, morning_yannic
from app.render.registry import DESIGNS, fetch_values, design_line
from app.templates import template_by_id, templates_for

GOLDEN = Path(__file__).parent / "golden" / "design" / "b4-014.bin"  # morning_yannic, Node reference
MORNING = template_by_id(7)
SYSTEM = morning_system(SAMPLE_MORNING)  # live Morning: the system design, no Node reference yet


class FakeClient:
    def __init__(self, states, fail=()):
        self.states = states
        self.fail = set(fail)

    def state(self, entity_id):
        if entity_id in self.fail:
            raise HAError(f"{entity_id}: Entity not found")
        return self.states[entity_id]


ALL_STATES = {
    "sensor.body_battery_most_recent": "72",
    "sensor.avg_stress_level": "24",
    "sensor.total_steps": "6120",
    "sensor.truenas_cpu_usage": "18",
    "sensor.system_monitor_memory_usage": "61",
}


def test_morning_is_a_yannic_template_that_feeds_one_line():
    assert MORNING.design == "morning" and MORNING.feed == 1
    assert MORNING in templates_for("yannic")
    assert all(t.design is None for t in templates_for("wife"))


def test_values_come_from_the_entity_map():
    values = fetch_values(DESIGNS["morning"], FakeClient(ALL_STATES))
    assert values == {"body_battery": 72.0, "stress": 24.0, "steps": 6120.0, "cpu": 18.0, "ram": 61.0}


def test_unavailable_or_missing_entities_are_none_and_print_no_data():
    states = dict(ALL_STATES, **{"sensor.total_steps": "unavailable"})
    values = fetch_values(DESIGNS["morning"], FakeClient(states, fail=["sensor.avg_stress_level"]))
    assert values["steps"] is None and values["stress"] is None

    line, all_missing = design_line("morning", SAMPLE_MORNING.summary, FakeClient(states, fail=["sensor.avg_stress_level"]))
    assert not all_missing
    expected = morning_system(replace(SAMPLE_MORNING, stress=None, steps=None))
    assert line.raster == (expected.width // 8, expected.height, expected.bits)


def test_no_home_assistant_means_every_value_is_no_data():
    line, all_missing = design_line("morning", "Hi", None)
    assert all_missing and line.raster is not None
    assert line.raster[0] == PAPER_DOTS // 8


def test_live_values_match_the_system_design():
    line, all_missing = design_line("morning", SAMPLE_MORNING.summary, FakeClient(ALL_STATES))
    assert not all_missing
    assert line.raster == (64, SYSTEM.height, SYSTEM.bits)


def test_image_ticket_prints_the_bitmap_then_a_one_line_feed_and_cut():
    line, _ = design_line("morning", SAMPLE_MORNING.summary, FakeClient(ALL_STATES))
    payload = encode([line], feed=MORNING.feed)
    assert SYSTEM.bits in payload
    assert payload.endswith(b"\x1bd\x01\x1dV\x01")


def test_image_ticket_is_queued_and_previewed_through_the_api(settings):
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app(settings)) as client:
        created = client.post(
            "/api/v1/tickets",
            json={"recipient": "yannic", "template": 7, "message": "Boiler serviced, bins out tonight."},
        )
        assert created.status_code == 201
        assert created.json()["template_id"] == 7
        preview = client.get(f"/api/v1/tickets/{created.json()['id']}/preview").text
        assert "[graph]" in preview


def test_system_tokens_and_manifest_load():
    assert system.card_radius() == 12
    assert system.spacing("m") == 12
    assert len([p for p in system.pieces().values()]) == 26
    assert system.decorations()["morning"]["hello"] in system.pieces()


def test_morning_card_carries_the_system_icon_and_it_is_data_driven(monkeypatch):
    with_icon = morning_system(SAMPLE_MORNING)
    monkeypatch.setitem(system.decorations(), "morning", {})
    without_icon = morning_system(SAMPLE_MORNING)
    assert with_icon.bits != without_icon.bits
    # The icon narrows the summary, so it can add one wrapped line (7 x 2 + 4 dots), no more.
    assert 0 <= with_icon.height - without_icon.height <= 7 * 2 + 4


def test_system_design_is_not_the_b4_014_reference():
    assert morning_system(SAMPLE_MORNING).bits != morning_yannic(SAMPLE_MORNING).bits
