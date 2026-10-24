"""Each tone looks different from every other tone: its header ornament and icon pair is unique."""

from app.render import strips


def test_no_two_tones_look_the_same():
    """Header, icon and title accent together identify a tone; no two tones may match on all three."""
    seen: dict[tuple[str, str, str], str] = {}
    for mood, spec in strips.MOODS.items():
        key = (spec["header"], spec["icon"], spec["accent"])
        assert key not in seen, f"{mood} and {seen[key]} look the same: {key}"
        seen[key] = mood


def test_only_the_critical_tone_is_inverted():
    """Inverted white-on-black titles are reserved for the super-urgent tone."""
    pills = sorted(mood for mood, spec in strips.MOODS.items() if spec["accent"] == "pill")
    assert pills == ["critical"]


def test_heart_is_only_for_loving():
    """A heart means love: it never appears on a reminder, a fact or a neutral ticket."""
    for mood, spec in strips.MOODS.items():
        has_heart = "heart" in (spec["header"], spec["icon"])
        assert has_heart == (mood == "loving"), mood


def test_urgent_has_the_barcode_border_and_gentle_has_the_zigzag():
    assert strips.MOODS["urgent"]["header"] == "barcode"
    assert strips.MOODS["gentle_warning"]["header"] == "dottedWave"


def test_urgent_tones_have_a_heavier_outline_and_soft_tones_a_rounder_one():
    """The card outline carries the tone: heavy and square for urgent, round for soft."""
    for mood in ("urgent", "critical"):
        assert strips.STROKE_BY_MOOD[mood] > strips.STROKE
        assert strips.RADIUS_BY_MOOD[mood] < strips.RADIUS
    for mood in ("loving", "gentle_warning"):
        assert strips.RADIUS_BY_MOOD[mood] > strips.RADIUS
    assert strips.STROKE_BY_MOOD["critical"] == max(strips.STROKE_BY_MOOD.values())
