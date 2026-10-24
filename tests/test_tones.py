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


FAMILIES = {
    "none": ("neutral", "factual"),
    "bandDots": ("loving", "happy"),
    "bandZigzag": ("excited", "playful"),
    "bandTicks": ("reminder",),
    "bandStipple": ("sad", "confused"),
    "bandHatch": ("gentle_warning", "upset"),
    "bandBlocks": ("firm_complaint",),
    "bandBarcode": ("urgent",),
    "bandFill": ("critical",),
}


def test_every_mood_belongs_to_one_family_with_its_own_band():
    """Six families, six bands: the band carries the mood, one per card at the top, nothing at the foot."""
    assert sorted(m for ms in FAMILIES.values() for m in ms) == sorted(strips.MOODS)
    for band, moods in FAMILIES.items():
        for mood in moods:
            assert strips.MOODS[mood]["header"] == band, mood
            assert strips.MOODS[mood]["divider"] == "none" and strips.MOODS[mood]["footer"] == "none", mood
    assert len(FAMILIES) == len({b for b in FAMILIES})


def test_bands_ink_rises_with_urgency():
    """Squint test: the bands get darker as urgency rises, ending in the solid bar."""
    from app.render.canvas import Canvas

    def ink(name: str) -> int:
        c = Canvas()
        strips.ORNAMENTS[name](c, 20, 490, 10)
        return sum(bin(b).count("1") for b in c.bits)

    inks = {b: ink(b) for b in FAMILIES if b != "none"}
    assert len(set(inks.values())) == len(inks)
    order = sorted(inks, key=inks.get)
    assert order[-2:] == ["bandBarcode", "bandFill"] and order[0] == "bandDots"


def test_urgent_tones_have_a_heavier_outline_and_soft_tones_a_rounder_one():
    """The card outline carries the tone: heavy and square for urgent, round for soft."""
    for mood in ("urgent", "critical"):
        assert strips.STROKE_BY_MOOD[mood] > strips.STROKE
        assert strips.RADIUS_BY_MOOD[mood] < strips.RADIUS
    for mood in ("loving", "gentle_warning"):
        assert strips.RADIUS_BY_MOOD[mood] > strips.RADIUS
    assert strips.STROKE_BY_MOOD["critical"] == max(strips.STROKE_BY_MOOD.values())
