from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

import pytest

from app.schedule import (
    DEFAULT_GRACE_MS,
    catch_up,
    idempotency_key,
    in_quiet_hours,
    latest_missed_run,
    local_to_utc_ms,
    next_after_quiet,
    next_daily_run_ms,
    parse_hhmm,
)

LONDON = ZoneInfo("Europe/London")


def utc(*args) -> int:
    return int(datetime(*args, tzinfo=UTC).timestamp() * 1000)


def iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_parse_hhmm_accepts_24_hour_times():
    assert parse_hhmm("07:05") == time(7, 5)
    assert parse_hhmm(" 23:59 ") == time(23, 59)


@pytest.mark.parametrize("value", ["7:05", "24:00", "12:60", "noon", ""])
def test_parse_hhmm_rejects_others(value):
    with pytest.raises(ValueError):
        parse_hhmm(value)


def test_daily_run_in_summer_is_bst():
    # 07:00 BST is 06:00 UTC.
    after = utc(2026, 7, 1, 5, 0)
    assert iso(next_daily_run_ms(time(7, 0), LONDON, after)) == "2026-07-01T06:00:00Z"


def test_daily_run_in_winter_is_gmt():
    after = utc(2026, 1, 15, 6, 30)
    assert iso(next_daily_run_ms(time(7, 0), LONDON, after)) == "2026-01-15T07:00:00Z"


def test_daily_run_is_strictly_after_the_last_run():
    run = next_daily_run_ms(time(7, 0), LONDON, utc(2026, 7, 1, 5, 0))
    assert iso(next_daily_run_ms(time(7, 0), LONDON, run)) == "2026-07-02T06:00:00Z"


def test_daily_run_keeps_wall_clock_across_spring_forward():
    # Clocks go forward on 2026-03-29 at 01:00 UTC. 07:00 the day before is GMT, the day
    # after is BST, so the UTC time moves from 07:00 to 06:00.
    before = utc(2026, 3, 28, 12, 0)
    first = next_daily_run_ms(time(7, 0), LONDON, before)
    second = next_daily_run_ms(time(7, 0), LONDON, first)
    assert iso(first) == "2026-03-29T06:00:00Z"
    assert iso(second) == "2026-03-30T06:00:00Z"


def test_gap_time_runs_at_the_shifted_time():
    # 01:30 does not exist on 2026-03-29. zoneinfo gives 02:30 BST, i.e. 01:30 UTC.
    assert iso(local_to_utc_ms(datetime(2026, 3, 29).date(), time(1, 30), LONDON)) == "2026-03-29T01:30:00Z"


def test_ambiguous_time_runs_once_on_fall_back_day():
    # 01:30 happens twice on 2026-10-25. The first occurrence (BST) is used, once.
    after = utc(2026, 10, 25, 0, 0)
    first = next_daily_run_ms(time(1, 30), LONDON, after)
    assert iso(first) == "2026-10-25T00:30:00Z"
    second = next_daily_run_ms(time(1, 30), LONDON, first)
    assert iso(second) == "2026-10-26T01:30:00Z"


def test_quiet_hours_within_one_day():
    tz = LONDON
    assert in_quiet_hours(utc(2026, 7, 1, 21, 30), time(9, 0), time(17, 0), tz) is False  # 22:30 BST
    assert in_quiet_hours(utc(2026, 7, 1, 10, 0), time(9, 0), time(17, 0), tz) is True  # 11:00 BST


def test_quiet_hours_cross_midnight():
    tz = LONDON
    start, end = time(23, 0), time(7, 0)
    assert in_quiet_hours(utc(2026, 7, 1, 21, 30), start, end, tz) is False  # 22:30 BST
    assert in_quiet_hours(utc(2026, 7, 1, 22, 30), start, end, tz) is True  # 23:30 BST
    assert in_quiet_hours(utc(2026, 7, 1, 23, 30), start, end, tz) is True  # 00:30 BST
    assert in_quiet_hours(utc(2026, 7, 1, 5, 30), start, end, tz) is True  # 06:30 BST
    assert in_quiet_hours(utc(2026, 7, 1, 6, 30), start, end, tz) is False  # 07:30 BST


def test_empty_quiet_window_never_matches():
    assert in_quiet_hours(utc(2026, 7, 1, 12, 0), time(8, 0), time(8, 0), LONDON) is False


def test_next_after_quiet_returns_end_of_window():
    # 00:30 BST on 2026-07-02 is inside 23:00 to 07:00, so the window ends at 07:00 BST.
    now = utc(2026, 7, 1, 23, 30)
    assert iso(next_after_quiet(now, time(23, 0), time(7, 0), LONDON)) == "2026-07-02T06:00:00Z"


def test_next_after_quiet_when_not_quiet_is_now():
    now = utc(2026, 7, 1, 12, 0)
    assert next_after_quiet(now, time(23, 0), time(7, 0), LONDON) == now


def test_catch_up_prints_inside_grace_and_skips_outside():
    scheduled = utc(2026, 7, 1, 6, 0)
    assert catch_up(scheduled, scheduled + DEFAULT_GRACE_MS) == "print"
    assert catch_up(scheduled, scheduled + DEFAULT_GRACE_MS + 1) == "skip"


def test_catch_up_grace_is_configurable():
    scheduled = utc(2026, 7, 1, 6, 0)
    assert catch_up(scheduled, scheduled + 5_000, grace_ms=1_000) == "skip"


def test_downtime_prints_only_the_newest_missed_run():
    # Last ran on 1 July, the server was down until 4 July at noon. Only 4 July 07:00 is returned.
    last = utc(2026, 7, 1, 6, 0)
    now = utc(2026, 7, 4, 11, 0)
    assert iso(latest_missed_run(time(7, 0), LONDON, last, now)) == "2026-07-04T06:00:00Z"


def test_no_missed_run_when_next_run_is_still_ahead():
    last = utc(2026, 7, 1, 6, 0)
    now = utc(2026, 7, 1, 12, 0)
    assert latest_missed_run(time(7, 0), LONDON, last, now) is None


def test_missed_run_with_no_history_uses_a_short_lookback():
    now = utc(2026, 7, 4, 11, 0)
    assert iso(latest_missed_run(time(7, 0), LONDON, 0, now)) == "2026-07-04T06:00:00Z"


def test_idempotency_key_is_stable_and_clean():
    assert idempotency_key("Morning", "yannic", "2026-10-26") == "morning:yannic:2026-10-26"
    assert idempotency_key("evening", " home arrival ") == "evening:home-arrival"


def test_idempotency_key_needs_a_part():
    with pytest.raises(ValueError):
        idempotency_key("  ")
