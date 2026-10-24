"""Fixes found while simulating a Hermes day: small values, unit spacing and the names on receipts."""

from datetime import UTC

from app.receipt import receipt_for_ticket
from app.slots import _number, slot_lines


def test_small_values_keep_their_digits():
    assert _number(0.079) == "0.079"
    assert _number(0.245) == "0.245"
    assert _number(6120.0) == "6120"
    assert _number(54.9) == "54.9"
    assert _number(19.5) == "19.5"


def test_letter_units_get_a_space_and_percent_does_not():
    texts = [line.text for line in slot_lines({"metrics": [{"label": "Steps", "value": 6120, "unit": "steps"}]})]
    assert any(text.endswith("6120 steps") for text in texts)
    texts = [line.text for line in slot_lines({"metrics": [{"label": "Battery", "value": 54, "unit": "%"}]})]
    assert any(text.endswith("54%") for text in texts)


def test_receipt_names_the_people_not_their_ids():
    ticket = {
        "recipient": "yannic",
        "message": "Thank you for the cookies",
        "sender": "hermes",
        "from_user": "wife",
        "title": None,
        "send_at_ms": 1_793_000_000_000,
    }
    receipt = receipt_for_ticket(ticket, UTC)
    assert receipt.recipient == "Yannic"
    assert receipt.sender == "Allyson"


def test_receipt_keeps_the_sender_when_no_person_sent_it():
    ticket = {
        "recipient": "wife",
        "message": "Reminder",
        "sender": "hermes",
        "from_user": None,
        "title": None,
        "send_at_ms": 1_793_000_000_000,
    }
    assert receipt_for_ticket(ticket, UTC).sender == "hermes"


def test_composed_entity_values_keep_small_digits():
    from app.compose import fetch_entities

    class Client:
        def state(self, entity_id):
            return "0.079"

    values = fetch_entities([{"type": "metric_rows", "slots": {"rows": [{"label": "Energy", "entity_id": "sensor.x"}]}}], Client())
    assert values == {"sensor.x": "0.079"}
