import pytest

from app.insights import (
    CATALOG,
    Candidate,
    InsightCache,
    build_insight,
    collect,
    rank,
    relevance_for,
    score_series,
)

STEADY = [50.0] * 29
OWN = Candidate("sensor.body_battery_most_recent", "Body battery", "%", "yannic", "body")
SHARED = Candidate("sensor.home_temperature", "Home", "°C", None, "house")
OTHER = Candidate("sensor.sleep_score_2", "Sleep score", "", "wife", "sleep")


def test_too_little_data_gives_nothing():
    assert score_series([1.0, 2.0]) is None
    assert build_insight(OWN, [1.0, 2.0], "yannic") is None


def test_unusual_latest_value_has_a_large_z_score():
    stats = score_series(STEADY[:20] + [60, 52, 48, 50, 90])
    assert stats is not None and stats["z"] > 2
    insight = build_insight(OWN, STEADY[:20] + [60, 52, 48, 50, 90], "yannic")
    assert insight.why == "well outside the usual range"


def test_flat_series_has_zero_z_and_is_steady():
    insight = build_insight(OWN, STEADY, "yannic")
    assert insight.z_score == 0
    assert insight.why == "steady"


def test_trend_up_when_last_week_is_higher():
    values = [40.0] * 21 + [60.0] * 7
    insight = build_insight(OWN, values, "yannic")
    assert insight.trend == "up"
    assert insight.trend_pct > 0


def test_relevance_prefers_own_then_shared():
    assert relevance_for(OWN, "yannic") == 3
    assert relevance_for(SHARED, "yannic") == 1
    assert relevance_for(SHARED, "wife") == 1


def test_other_persons_data_is_excluded():
    assert build_insight(OTHER, STEADY, "yannic") is None


def test_own_data_outranks_equally_unusual_shared_data():
    values = STEADY[:20] + [60, 52, 48, 50, 90]
    own = build_insight(OWN, values, "yannic")
    shared = build_insight(SHARED, values, "yannic")
    assert own.score > shared.score


def test_rank_returns_highest_scores_first_and_respects_limit():
    items = [
        build_insight(OWN, STEADY[:20] + [60, 52, 48, 50, 90], "yannic"),
        build_insight(SHARED, STEADY, "yannic"),
        build_insight(OWN, STEADY, "yannic"),
    ]
    top = rank(items, 2)
    assert len(top) == 2
    assert top[0].score >= top[1].score


def test_collect_skips_entities_that_fail_to_load():
    def history(entity_id, hours):
        if entity_id == "sensor.body_battery_most_recent":
            raise OSError("gone")
        return STEADY

    results = collect("yannic", history, limit=50)
    assert all(r.entity_id != "sensor.body_battery_most_recent" for r in results)
    assert results  # the rest still come back


def test_catalog_has_no_duplicate_ids_per_owner():
    keys = [(c.entity_id, c.owner) for c in CATALOG]
    assert len(keys) == len(set(keys))


def test_cache_reuses_answers_inside_the_ttl():
    now = [0.0]
    cache = InsightCache(clock=lambda: now[0])
    calls = []

    def compute():
        calls.append(1)
        return ["answer"]

    assert cache.get("yannic", 12, compute) == ["answer"]
    now[0] = 299.0
    assert cache.get("yannic", 12, compute) == ["answer"]
    assert len(calls) == 1
    now[0] = 301.0
    cache.get("yannic", 12, compute)
    assert len(calls) == 2


def test_cache_keys_by_person_and_limit():
    cache = InsightCache(clock=lambda: 0.0)
    assert cache.get("yannic", 12, lambda: ["a"]) == ["a"]
    assert cache.get("wife", 12, lambda: ["b"]) == ["b"]
    assert cache.get("yannic", 4, lambda: ["c"]) == ["c"]
