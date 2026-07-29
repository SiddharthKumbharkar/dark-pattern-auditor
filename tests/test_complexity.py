from signals.complexity import (
    compute_complexity_metrics,
    count_double_negatives,
    count_negations,
    flesch_kincaid_grade,
    is_consent_or_cancellation_copy,
)


def test_flesch_kincaid_simple_text_scores_low_grade():
    simple = "The cat sat on the mat. It was a warm day."
    complex_text = (
        "Notwithstanding the aforementioned stipulations, the undersigned "
        "party acknowledges the irrevocable relinquishment of entitlements "
        "pursuant to subsection fourteen."
    )
    simple_grade = flesch_kincaid_grade(simple)
    complex_grade = flesch_kincaid_grade(complex_text)
    assert simple_grade is not None and complex_grade is not None
    assert simple_grade < complex_grade


def test_flesch_kincaid_empty_text_is_null():
    assert flesch_kincaid_grade("") is None
    assert flesch_kincaid_grade("   ") is None


def test_count_negations():
    assert count_negations("I do not want this. I never agreed.") == 2
    assert count_negations("Yes please") == 0


def test_count_double_negatives_requires_two_in_one_sentence():
    assert count_double_negatives("I don't not want this.") == 1
    assert count_double_negatives("I do not want this. I never agreed.") == 0  # one negation per sentence


def test_is_consent_or_cancellation_copy():
    assert is_consent_or_cancellation_copy("Please accept our cookie policy") is True
    assert is_consent_or_cancellation_copy("Cancel your subscription below") is True
    assert is_consent_or_cancellation_copy("Buy the Pro X headphones now") is False


def test_compute_complexity_metrics_option_counts():
    steps = [{"step_id": 1, "action": {"type": "click"}, "timestamp": "2026-01-01T00:00:00+00:00"}]
    result = compute_complexity_metrics(steps, [None], [4])
    assert result["option_counts"] == [{"step_id": 1, "option_count": 4}]


def test_compute_complexity_metrics_skips_non_consent_copy_for_readability():
    steps = [{"step_id": 1, "action": {"type": "click"}, "timestamp": "2026-01-01T00:00:00+00:00"}]
    result = compute_complexity_metrics(steps, ["Buy our headphones today"], [2])
    assert result["copy_readability"] == []


def test_compute_complexity_metrics_includes_cancellation_copy_readability():
    steps = [{"step_id": 1, "action": {"type": "click"}, "timestamp": "2026-01-01T00:00:00+00:00"}]
    result = compute_complexity_metrics(steps, ["Are you sure you do not want to not cancel your plan?"], [2])
    assert len(result["copy_readability"]) == 1
    entry = result["copy_readability"][0]
    assert entry["step_id"] == 1
    assert entry["negation_count"] >= 2
    assert entry["double_negative_count"] >= 1


def test_time_on_step_computed_from_timestamps():
    steps = [
        {"step_id": 1, "action": {"type": "navigate"}, "timestamp": "2026-01-01T00:00:00+00:00"},
        {"step_id": 2, "action": {"type": "click"}, "timestamp": "2026-01-01T00:00:05+00:00"},
    ]
    result = compute_complexity_metrics(steps, [None, None], [None, None])
    assert result["time_on_step"] == [{"step_id": 2, "seconds": 5.0}]


def test_total_actions_required_excludes_navigate_and_unknown():
    steps = [
        {"step_id": 1, "action": {"type": "navigate"}, "timestamp": "2026-01-01T00:00:00+00:00"},
        {"step_id": 2, "action": {"type": "click"}, "timestamp": "2026-01-01T00:00:01+00:00"},
        {"step_id": 3, "action": {"type": "input"}, "timestamp": "2026-01-01T00:00:02+00:00"},
        {"step_id": 4, "action": {"type": "unknown"}, "timestamp": "2026-01-01T00:00:03+00:00"},
    ]
    result = compute_complexity_metrics(steps, [None] * 4, [None] * 4)
    assert result["total_actions_required"] == 2
