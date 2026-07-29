from journey.baselines import Baseline
from signals.claim_persistence import compute_claim_persistence, evaluate_claim_persistence, group_claims_by_identity

UNCHANGED_THRESHOLD = Baseline(median=24.0, p25=12.0, p75=48.0, n=10)
MIN_ELAPSED_THRESHOLD = Baseline(median=1.0, p25=0.5, p75=4.0, n=10)


def _claim(claim_type, selector, value, text=None):
    return {"claim_type": claim_type, "selector": selector, "normalized_value": value, "claim_text": text or f"{value}"}


def _revisit(index, timestamp, claims):
    return {"revisit_index": index, "timestamp": timestamp, "claims": claims}


def test_groups_claims_by_type_and_selector():
    episodes = [
        _revisit(0, "2026-01-01T00:00:00+00:00", [_claim("stock_count", "#a", 5)]),
        _revisit(1, "2026-01-02T00:00:00+00:00", [_claim("stock_count", "#a", 3)]),
    ]
    grouped = group_claims_by_identity(episodes)
    assert list(grouped.keys()) == [("stock_count", "#a")]
    assert [r["revisit_index"] for r in grouped[("stock_count", "#a")]] == [0, 1]


def test_claim_with_no_selector_is_dropped():
    episodes = [_revisit(0, "2026-01-01T00:00:00+00:00", [_claim("urgency_phrase", None, None)])]
    assert group_claims_by_identity(episodes) == {}


def test_stock_count_decreasing_is_verified_true():
    revisits = [
        {"revisit_index": 0, "timestamp": "2026-01-01T00:00:00+00:00", "claim_text": "5 left", "normalized_value": 5},
        {"revisit_index": 1, "timestamp": "2026-01-03T00:00:00+00:00", "claim_text": "2 left", "normalized_value": 2},
    ]
    result = evaluate_claim_persistence("stock_count", "#a", revisits, UNCHANGED_THRESHOLD, MIN_ELAPSED_THRESHOLD)
    assert result["verdict"] == "verified_true"
    assert result["plausible_change"] is True
    assert result["unchanged_across_revisits"] is False


def test_stock_count_increasing_is_implausible():
    revisits = [
        {"revisit_index": 0, "timestamp": "2026-01-01T00:00:00+00:00", "claim_text": "2 left", "normalized_value": 2},
        {"revisit_index": 1, "timestamp": "2026-01-03T00:00:00+00:00", "claim_text": "9 left", "normalized_value": 9},
    ]
    result = evaluate_claim_persistence("stock_count", "#a", revisits, UNCHANGED_THRESHOLD, MIN_ELAPSED_THRESHOLD)
    assert result["verdict"] == "implausible"
    assert result["plausible_change"] is False


def test_stock_count_unchanged_beyond_threshold_is_implausible():
    revisits = [
        {"revisit_index": 0, "timestamp": "2026-01-01T00:00:00+00:00", "claim_text": "2 left", "normalized_value": 2},
        {"revisit_index": 1, "timestamp": "2026-01-04T00:00:00+00:00", "claim_text": "2 left", "normalized_value": 2},  # 72h later
    ]
    result = evaluate_claim_persistence("stock_count", "#a", revisits, UNCHANGED_THRESHOLD, MIN_ELAPSED_THRESHOLD)
    assert result["unchanged_across_revisits"] is True
    assert result["verdict"] == "implausible"
    assert result["plausible_change"] is False


def test_stock_count_unchanged_within_threshold_is_verified_true():
    revisits = [
        {"revisit_index": 0, "timestamp": "2026-01-01T00:00:00+00:00", "claim_text": "2 left", "normalized_value": 2},
        {"revisit_index": 1, "timestamp": "2026-01-01T02:00:00+00:00", "claim_text": "2 left", "normalized_value": 2},  # 2h later
    ]
    result = evaluate_claim_persistence("stock_count", "#a", revisits, UNCHANGED_THRESHOLD, MIN_ELAPSED_THRESHOLD)
    assert result["verdict"] == "verified_true"


def test_single_revisit_is_insufficient_data():
    revisits = [{"revisit_index": 0, "timestamp": "2026-01-01T00:00:00+00:00", "claim_text": "2 left", "normalized_value": 2}]
    result = evaluate_claim_persistence("stock_count", "#a", revisits, UNCHANGED_THRESHOLD, MIN_ELAPSED_THRESHOLD)
    assert result["verdict"] == "insufficient_data"
    assert result["plausible_change"] is None


def test_too_little_elapsed_time_is_insufficient_data():
    revisits = [
        {"revisit_index": 0, "timestamp": "2026-01-01T00:00:00+00:00", "claim_text": "2 left", "normalized_value": 2},
        {"revisit_index": 1, "timestamp": "2026-01-01T00:05:00+00:00", "claim_text": "2 left", "normalized_value": 2},  # 5 min later
    ]
    result = evaluate_claim_persistence("stock_count", "#a", revisits, UNCHANGED_THRESHOLD, MIN_ELAPSED_THRESHOLD)
    assert result["verdict"] == "insufficient_data"


def test_verdict_never_reports_false():
    # Sweep a range of scenarios and confirm "false" (the literal string)
    # never appears as a verdict -- only implausible/verified_true/insufficient_data.
    scenarios = [
        [{"revisit_index": 0, "timestamp": "2026-01-01T00:00:00+00:00", "claim_text": "x", "normalized_value": 5}],
        [
            {"revisit_index": 0, "timestamp": "2026-01-01T00:00:00+00:00", "claim_text": "x", "normalized_value": 5},
            {"revisit_index": 1, "timestamp": "2026-01-04T00:00:00+00:00", "claim_text": "x", "normalized_value": 9},
        ],
        [
            {"revisit_index": 0, "timestamp": "2026-01-01T00:00:00+00:00", "claim_text": "x", "normalized_value": 5},
            {"revisit_index": 1, "timestamp": "2026-01-04T00:00:00+00:00", "claim_text": "x", "normalized_value": 5},
        ],
    ]
    for revisits in scenarios:
        result = evaluate_claim_persistence("stock_count", "#a", revisits, UNCHANGED_THRESHOLD, MIN_ELAPSED_THRESHOLD)
        assert result["verdict"] in ("verified_true", "implausible", "insufficient_data")
        assert result["verdict"] != "false"


def test_compute_claim_persistence_end_to_end_over_three_revisits():
    episodes = [
        _revisit(0, "2026-01-01T00:00:00+00:00", [_claim("stock_count", "#stock", 10), _claim("viewer_count", "#viewers", 5)]),
        _revisit(1, "2026-01-02T00:00:00+00:00", [_claim("stock_count", "#stock", 7), _claim("viewer_count", "#viewers", 5)]),
        _revisit(2, "2026-01-05T00:00:00+00:00", [_claim("stock_count", "#stock", 3), _claim("viewer_count", "#viewers", 5)]),
    ]
    results = compute_claim_persistence(episodes, UNCHANGED_THRESHOLD, MIN_ELAPSED_THRESHOLD)
    by_selector = {r["selector"]: r for r in results}
    assert by_selector["#stock"]["verdict"] == "verified_true"
    assert by_selector["#stock"]["revisit_indices"] == [0, 1, 2]
    # viewer count frozen at 5 across ~4 days -- beyond the 24h threshold
    assert by_selector["#viewers"]["unchanged_across_revisits"] is True
    assert by_selector["#viewers"]["verdict"] == "implausible"
