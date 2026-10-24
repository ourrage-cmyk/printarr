"""Each tone looks different from every other tone: its header ornament and icon pair is unique."""

from app.render import strips


def test_no_two_tones_share_header_and_icon():
    seen: dict[tuple[str, str], str] = {}
    for mood, spec in strips.MOODS.items():
        key = (spec["header"], spec["icon"])
        assert key not in seen, f"{mood} and {seen[key]} share header {key[0]} and icon {key[1]}"
        seen[key] = mood


def test_pills_are_only_for_the_two_strongest_tones():
    pills = sorted(mood for mood, spec in strips.MOODS.items() if spec["accent"] == "pill")
    assert pills == ["excited", "urgent"]
