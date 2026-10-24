"""Each kind of ticket wears its own mark, so a note, alert, reminder, fun fact and shopping list differ at a glance."""

import pytest

from app.render import strips
from app.render import strips as S
from app.render.strips import Block

KINDS = {
    "message": {"title": "Parcel", "paragraph": "Parcel is at the back door.", "from": "Yannic"},
    "alert": {"label": "Water leak", "paragraph": "Kitchen sensor is wet.", "action": "Turn off the tap"},
    "tip": {"tip": "Bins go out tonight."},
    "fact": {"paragraph": "A dot matrix head prints one row at a time."},
    "checklist": {"title": "Shopping", "items": [{"text": "Milk", "checked": False}]},
}


@pytest.fixture
def stamped(monkeypatch):
    names: list[str] = []
    original = S.stamp_sprite

    def recording(c, x, y, name, scale=3):
        names.append(name)
        return original(c, x, y, name, scale)

    monkeypatch.setattr(S, "stamp_sprite", recording)
    return names


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_each_kind_stamps_its_own_mark(kind, stamped):
    strips.render_strip([Block(kind, KINDS[kind])])
    assert strips.KIND_MARKS[kind] in stamped


def test_kind_marks_are_all_different():
    marks = list(strips.KIND_MARKS.values())
    assert len(marks) == len(set(marks))


def test_no_kind_mark_is_a_heart_or_a_star():
    assert not {"heart", "star"} & set(strips.KIND_MARKS.values())


@pytest.mark.parametrize("name", sorted(strips.KIND_MARKS.values()))
def test_mark_sprites_are_rectangular(name):
    widths = {len(row) for row in strips.SPRITES[name]}
    assert len(widths) == 1, f"{name} has rows of different widths: {widths}"
