from app.render import strips


def test_a_unit_never_splits_from_its_number():
    # "OUTSIDE, 24 H" used to break as "OUTSIDE, 24" / "H"; the unit now stays with its number.
    for width in (300, 330, 360, 400, 420):
        _, lines = strips.title_lines("Outside, 24 h", width)
        assert all(line.split()[-1] != "24" for line in lines if line.split()), (width, lines)
        assert lines[-1].endswith("24 H") or lines[-1] == "24 H", (width, lines)


def test_a_single_short_word_is_not_left_alone_on_a_line():
    lines = strips._no_orphan(["OUTSIDE, 24", "H"], 20)
    assert lines == ["OUTSIDE,", "24 H"]
    # a line with no word before the short one stays as it is
    assert strips._no_orphan(["ABCDEFGHIJKLMNOP", "M"], 10) == ["ABCDEFGHIJKLMNOP", "M"]
    # the pair must still fit on one line; otherwise the lines are left as they are
    assert strips._no_orphan(["ABCDEFGHIJ KLMNOPQ", "R"], 8) == ["ABCDEFGHIJ KLMNOPQ", "R"]
