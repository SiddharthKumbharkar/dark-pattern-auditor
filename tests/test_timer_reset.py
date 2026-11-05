from journey.baselines import Baseline
from signals.timer_reset import detect_timer_resets

TOLERANCE = Baseline(median=30.0, p25=10.0, p75=60.0, n=10)


def _revisit(index, timestamp, remaining):
    return {"revisit_index": index, "timestamp": timestamp, "remaining_seconds": remaining}


def test_genuine_countdown_tracking_wall_clock_is_not_flagged():
    # 1 hour remaining at revisit 0; 30 minutes later, ~30 minutes remain.
    revisits = [
        _revisit(0, "2026-01-01T00:00:00+00:00", 3600),
        _revisit(1, "2026-01-01T00:30:00+00:00", 1800),
    ]
    results = detect_timer_resets(revisits, TOLERANCE)
    assert len(results) == 1
    assert results[0]["reset_detected"] is False


def test_timer_not_decreasing_at_all_is_flagged():
    revisits = [
        _revisit(0, "2026-01-01T00:00:00+00:00", 3600),
        _revisit(1, "2026-01-01T01:00:00+00:00", 3600),  # still "1 hour left" an hour later
    ]
    results = detect_timer_resets(revisits, TOLERANCE)
    assert results[0]["reset_detected"] is True


def test_timer_increasing_is_flagged():
    revisits = [
        _revisit(0, "2026-01-01T00:00:00+00:00", 1800),
        _revisit(1, "2026-01-01T00:10:00+00:00", 3600),  # went UP
    ]
    results = detect_timer_resets(revisits, TOLERANCE)
    assert results[0]["reset_detected"] is True


def test_small_deviation_within_tolerance_is_not_flagged():
    # expected ~1770s remaining (1800 - 30s elapsed); observed 1790s --
    # 20s off, within the 30s median tolerance.
    revisits = [
        _revisit(0, "2026-01-01T00:00:00+00:00", 1800),
        _revisit(1, "2026-01-01T00:00:30+00:00", 1790),
    ]
    results = detect_timer_resets(revisits, TOLERANCE)
    assert results[0]["reset_detected"] is False


def test_multiple_consecutive_pairs_produce_multiple_records():
    revisits = [
        _revisit(0, "2026-01-01T00:00:00+00:00", 3600),
        _revisit(1, "2026-01-01T00:30:00+00:00", 1800),
        _revisit(2, "2026-01-01T01:00:00+00:00", 1200),
    ]
    results = detect_timer_resets(revisits, TOLERANCE)
    assert len(results) == 2
    assert [r["from_revisit_index"] for r in results] == [0, 1]


def test_missing_remaining_seconds_is_skipped_not_a_crash():
    revisits = [
        _revisit(0, "2026-01-01T00:00:00+00:00", None),
        _revisit(1, "2026-01-01T00:30:00+00:00", 1800),
    ]
    assert detect_timer_resets(revisits, TOLERANCE) == []


def test_single_revisit_produces_no_comparisons():
    assert detect_timer_resets([_revisit(0, "2026-01-01T00:00:00+00:00", 3600)], TOLERANCE) == []
