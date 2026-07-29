import json
import os

import pytest

from journey.baselines import BaselineStore, _percentile


def test_percentile_median_of_odd_list():
    assert _percentile([1, 2, 3, 4, 5], 50) == 3


def test_percentile_p25_p75_known_values():
    values = [10, 20, 30, 40]
    assert _percentile(values, 25) == 17.5
    assert _percentile(values, 75) == 32.5


def test_loads_seed_when_no_file_present(tmp_path):
    store = BaselineStore(path=os.path.join(str(tmp_path), "does_not_exist.json"))
    baseline = store.get("claim_unchanged_hours_before_implausible")
    assert baseline.n == 0
    assert baseline.is_seed() is True


def test_unknown_key_raises_clear_error(tmp_path):
    store = BaselineStore(path=os.path.join(str(tmp_path), "does_not_exist.json"))
    with pytest.raises(KeyError):
        store.get("no_such_baseline_key")


def test_set_from_samples_computes_real_distribution(tmp_path):
    store = BaselineStore(path=os.path.join(str(tmp_path), "baselines.json"))
    baseline = store.set_from_samples("timer_drift_tolerance_seconds", [10, 20, 30, 40, 50])
    assert baseline.median == 30
    assert baseline.n == 5
    assert baseline.is_seed() is False


def test_save_and_reload_round_trips(tmp_path):
    path = os.path.join(str(tmp_path), "baselines.json")
    store = BaselineStore(path=path)
    store.set_from_samples("timer_drift_tolerance_seconds", [5, 15, 25])
    store.save()

    reloaded = BaselineStore(path=path)
    baseline = reloaded.get("timer_drift_tolerance_seconds")
    assert baseline.n == 3
    assert baseline.median == 15


def test_save_only_writes_the_target_file(tmp_path):
    path = os.path.join(str(tmp_path), "baselines.json")
    store = BaselineStore(path=path)
    store.set_from_samples("claim_unchanged_hours_before_implausible", [1, 2, 3])
    store.save()
    with open(path) as f:
        data = json.load(f)
    assert data["claim_unchanged_hours_before_implausible"]["n"] == 3


def test_real_repo_baselines_json_loads_and_has_seed_keys():
    store = BaselineStore()
    for key in ("claim_unchanged_hours_before_implausible", "timer_drift_tolerance_seconds", "claim_min_elapsed_hours_for_verdict"):
        baseline = store.get(key)
        assert baseline.median > 0


# -- goal-scoped lookup ---------------------------------------------------


def test_goal_scoped_lookup_falls_back_to_global_when_no_override_exists(tmp_path):
    store = BaselineStore(path=os.path.join(str(tmp_path), "baselines.json"))
    store.set_from_samples("some_key", [1, 2, 3])
    global_baseline = store.get("some_key")
    goal_baseline = store.get("some_key", goal="some_goal")
    assert goal_baseline == global_baseline


def test_goal_scoped_override_takes_priority_over_global(tmp_path):
    store = BaselineStore(path=os.path.join(str(tmp_path), "baselines.json"))
    store.set_from_samples("some_key", [1, 2, 3])
    store.set_from_samples("some_key", [100, 200, 300], goal="cancel_subscription")

    assert store.get("some_key").median == 2
    assert store.get("some_key", goal="cancel_subscription").median == 200
    assert store.get("some_key", goal="unrelated_goal").median == 2  # still falls back


def test_goal_scoped_set_and_reload_round_trips(tmp_path):
    path = os.path.join(str(tmp_path), "baselines.json")
    store = BaselineStore(path=path)
    store.set_from_samples("complexity_reading_grade_threshold", [16, 18, 20], goal="cancel_subscription")
    store.save()

    reloaded = BaselineStore(path=path)
    assert reloaded.get("complexity_reading_grade_threshold", goal="cancel_subscription").median == 18
    assert reloaded.get("complexity_reading_grade_threshold").median == 12.0  # global seed, untouched


def test_real_repo_baselines_json_has_a_goal_scoped_complexity_entry():
    store = BaselineStore()
    global_baseline = store.get("complexity_reading_grade_threshold")
    goal_baseline = store.get("complexity_reading_grade_threshold", goal="cancel_subscription")
    assert goal_baseline.median != global_baseline.median
