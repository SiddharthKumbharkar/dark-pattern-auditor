"""Tests for journey/ground_truth.py: loading/validating ground_truth.yaml,
mode inference, and validate_against_truth()'s precision/recall/F1 math --
plus an end-to-end pass through the real recorded pipeline (evidence +
attributes) for both an ON-mode and OFF-mode synthetic episode, and CLI
smoke tests for validate_against_truth.py.
"""

import os
import subprocess
import sys

import pytest
import yaml

from attribute_agents.base import ATTRIBUTES
from config.settings import Config
from journey.attribute_runner import run_attributes
from journey.evidence_extractor import extract_evidence
from journey.ground_truth import (
    GroundTruthError,
    infer_mode,
    load_ground_truth,
    validate_against_truth,
)
from journey.schema_migration import load_episode
from recorder.interactive_v2 import InteractiveRecorderV2

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL_GROUND_TRUTH_PATH = os.path.join(REPO_ROOT, "ground_truth.yaml")


# -- loading / validating ground_truth.yaml --------------------------------


def test_the_real_ground_truth_file_loads_and_has_exactly_12_patterns():
    doc = load_ground_truth(REAL_GROUND_TRUTH_PATH)
    assert len(doc["patterns"]) == 12
    assert len({p["pattern_id"] for p in doc["patterns"]}) == 12


def test_every_expected_attribute_in_the_real_file_is_a_known_attribute():
    doc = load_ground_truth(REAL_GROUND_TRUTH_PATH)
    for pattern in doc["patterns"]:
        for attribute in pattern["expected_attributes"]:
            assert attribute in ATTRIBUTES


def test_missing_file_is_rejected(tmp_path):
    with pytest.raises(GroundTruthError, match="not found"):
        load_ground_truth(str(tmp_path / "nope.yaml"))


def test_missing_required_field_is_rejected(tmp_path):
    bad = {"patterns": [{"pattern_id": "x", "name": "x"}]}
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.dump(bad))
    with pytest.raises(GroundTruthError, match="missing field"):
        load_ground_truth(str(path))


def test_unknown_expected_attribute_is_rejected(tmp_path):
    bad = {"patterns": [{
        "pattern_id": "x", "name": "x", "ccpa_category": "x", "goal": None,
        "expected_steps_hint": "x", "expected_attributes": ["not_a_real_attribute"],
        "enabled_when": "on", "requires_revisit": False, "known_gap": None,
    }]}
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.dump(bad))
    with pytest.raises(GroundTruthError, match="unknown attribute"):
        load_ground_truth(str(path))


def test_enabled_when_off_is_rejected(tmp_path):
    bad = {"patterns": [{
        "pattern_id": "x", "name": "x", "ccpa_category": "x", "goal": None,
        "expected_steps_hint": "x", "expected_attributes": [],
        "enabled_when": "off", "requires_revisit": False, "known_gap": None,
    }]}
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.dump(bad))
    with pytest.raises(GroundTruthError, match='"on"'):
        load_ground_truth(str(path))


def test_duplicate_pattern_id_is_rejected(tmp_path):
    entry = {
        "pattern_id": "dup", "name": "x", "ccpa_category": "x", "goal": None,
        "expected_steps_hint": "x", "expected_attributes": [],
        "enabled_when": "on", "requires_revisit": False, "known_gap": None,
    }
    bad = {"patterns": [entry, dict(entry)]}
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.dump(bad))
    with pytest.raises(GroundTruthError, match="duplicate"):
        load_ground_truth(str(path))


# -- mode inference ----------------------------------------------------


def test_infer_mode_localhost_is_on():
    assert infer_mode({"episode": {"site_domain": "auralis-on.local"}}) == "on"


def test_infer_mode_127_is_off():
    assert infer_mode({"episode": {"site_domain": "auralis-off.local"}}) == "off"


def test_infer_mode_unknown_domain_is_none():
    assert infer_mode({"episode": {"site_domain": "example.com"}}) is None


# -- validate_against_truth() pure logic (hand-built episode dicts) -------


def _episode(goal, site_domain, results):
    return {
        "episode": {"episode_id": "e1", "goal": goal, "site_domain": site_domain},
        "attributes": {"results": [
            {"attribute": a, "verdict": v, "severity": None, "confidence": 0.5,
             "evidence_pointers": [], "reasoning": "x", "agent_version": "x", "agent_type": "code"}
            for a, v in results.items()
        ]},
    }


@pytest.fixture
def ground_truth():
    return load_ground_truth(REAL_GROUND_TRUTH_PATH)


def test_off_mode_expects_nothing_any_fire_is_a_false_positive(ground_truth):
    episode = _episode("purchase_cheapest", "auralis-off.local", {"asymmetry": "fires"})
    result = validate_against_truth(episode, ground_truth)
    assert result["mode"] == "off"
    row = next(r for r in result["rows"] if r["attribute"] == "asymmetry")
    assert row["expected"] is False
    assert row["classification"] == "FP"
    assert result["fp"] == 1
    assert result["precision"] == 0.0
    assert result["recall"] is None  # no expected positives at all -- undefined, not 0.0


def test_on_mode_purchase_cheapest_expects_deception_and_information_hiding(ground_truth):
    episode = _episode("purchase_cheapest", "auralis-on.local", {})
    result = validate_against_truth(episode, ground_truth)
    expected_true = {r["attribute"] for r in result["rows"] if r["expected"]}
    assert expected_true == {"deception", "information_hiding"}


def test_information_hiding_miss_cites_the_known_stub_gap(ground_truth):
    episode = _episode("purchase_cheapest", "auralis-on.local", {})
    result = validate_against_truth(episode, ground_truth)
    row = next(r for r in result["rows"] if r["attribute"] == "information_hiding")
    assert row["classification"] == "FN"
    assert "Stage-2" in row["notes"]


def test_deception_miss_cites_requires_revisit(ground_truth):
    episode = _episode("purchase_cheapest", "auralis-on.local", {})
    result = validate_against_truth(episode, ground_truth)
    row = next(r for r in result["rows"] if r["attribute"] == "deception")
    assert row["classification"] == "FN"
    assert "revisit" in row["notes"]


def test_cancel_subscription_true_positive_on_the_two_code_first_expected_attributes(ground_truth):
    # cancel_subscription now expects all 7 attributes (one planted
    # instance of each lives in this goal after the enrichment pass --
    # see interface_interference_cancel_maze, deception_dead_unsubscribe_control,
    # complexity_overloaded_exit_survey, covertness_camouflaged_winback_optin,
    # and information_hiding_late_cancellation_fee in ground_truth.yaml).
    # This fixture only fires the two code-first ones asymmetry/restriction
    # detect on their own -- precision stays perfect (nothing false-fired),
    # recall reflects the other 5 (3 Stage-2-only stubs + deception +
    # complexity) not having fired in THIS minimal fixture.
    episode = _episode("cancel_subscription", "auralis-on.local", {"asymmetry": "fires", "restriction": "fires"})
    result = validate_against_truth(episode, ground_truth)
    assert result["tp"] == 2
    assert result["fn"] == 5
    assert result["precision"] == 1.0
    assert result["recall"] == pytest.approx(2 / 7)


def test_unresolvable_mode_raises(ground_truth):
    episode = _episode("purchase_cheapest", "some-other-host", {})
    with pytest.raises(GroundTruthError, match="could not determine"):
        validate_against_truth(episode, ground_truth)


def test_explicit_mode_overrides_site_domain_inference(ground_truth):
    episode = _episode("purchase_cheapest", "some-other-host", {})
    result = validate_against_truth(episode, ground_truth, mode="off")
    assert result["mode"] == "off"


def test_global_patterns_apply_regardless_of_goal(ground_truth):
    # confirm_shaming_popup and nagging_modal have goal: null -- they must
    # be included in _applicable_patterns for EVERY goal, even though both
    # currently contribute empty expected_attributes.
    for goal in ("purchase_cheapest", "complete_signup", "cancel_subscription", "decline_addon"):
        episode = _episode(goal, "auralis-on.local", {})
        result = validate_against_truth(episode, ground_truth)
        assert isinstance(result["rows"], list) and len(result["rows"]) == len(ATTRIBUTES)


# -- real recorded pipeline end-to-end ----------------------------------

SIGNUP_HTML = """<!DOCTYPE html>
<html><body>
<h1>Create your account</h1>
<button id="accept-btn" type="button"
  style="background:#000;color:#fff;font-size:20px;padding:14px;">Yes, sign me up</button>
<button id="reject-btn" type="button"
  style="background:#f5f5f5;color:#f0f0f0;font-size:8px;padding:2px;">No thanks</button>
</body></html>
"""


@pytest.fixture
def site_dir(tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    (site / "page.html").write_text(SIGNUP_HTML, encoding="utf-8")
    return site


def _record(storage_dir, episode_id, site_url, site_domain, goal_id):
    rec = InteractiveRecorderV2(
        storage_dir=storage_dir, episode_id=episode_id, site_url=site_url,
        site_domain=site_domain, sector="ecommerce", goal_id=goal_id,
        goal_description="ground truth e2e test", operator="test-operator",
        config=Config(), paired_episode_id=None,
    )
    rec.launch(headless=True)
    try:
        rec._poll_tick()
    finally:
        rec._teardown_browser()
        rec._cleanup_raw_artifacts()
    rec.finalize()
    return rec.episode_dir


def test_real_pipeline_on_and_off_episode_end_to_end(tmp_path, site_dir, ground_truth):
    storage_dir = str(tmp_path / "storage")

    on_dir = _record(storage_dir, "episode_gt_on", (site_dir / "page.html").as_uri(), "auralis-on.local", "cancel_subscription")
    off_dir = _record(storage_dir, "episode_gt_off", (site_dir / "page.html").as_uri(), "auralis-off.local", "cancel_subscription")

    extract_evidence(on_dir)
    extract_evidence(off_dir)
    run_attributes(on_dir, storage_dir=storage_dir)
    run_attributes(off_dir, storage_dir=storage_dir)

    on_episode = load_episode(os.path.join(on_dir, "episode.json"))
    off_episode = load_episode(os.path.join(off_dir, "episode.json"))

    on_result = validate_against_truth(on_episode, ground_truth)
    off_result = validate_against_truth(off_episode, ground_truth)

    assert on_result["mode"] == "on"
    assert off_result["mode"] == "off"
    # asymmetry pair on this fixture (contrast/area/font all skewed) really
    # does fire under the real AsymmetryAgent -- cancel_subscription expects it.
    on_asymmetry = next(r for r in on_result["rows"] if r["attribute"] == "asymmetry")
    assert on_asymmetry["code_verdict"] == "fires"
    assert on_asymmetry["classification"] == "TP"

    # off_result: same page content everywhere -- mode=off means expected
    # is empty regardless, so ANY fire here is correctly flagged as FP.
    off_asymmetry = next(r for r in off_result["rows"] if r["attribute"] == "asymmetry")
    assert off_asymmetry["expected"] is False
    if off_asymmetry["code_verdict"] == "fires":
        assert off_asymmetry["classification"] == "FP"


# -- CLI smoke tests -----------------------------------------------------


def test_cli_reports_a_table_and_metrics(tmp_path, site_dir):
    storage_dir = str(tmp_path / "storage")
    on_dir = _record(storage_dir, "episode_gt_cli", (site_dir / "page.html").as_uri(), "auralis-on.local", "cancel_subscription")
    extract_evidence(on_dir)
    run_attributes(on_dir, storage_dir=storage_dir)

    result = subprocess.run(
        [sys.executable, os.path.join(REPO_ROOT, "validate_against_truth.py"),
         on_dir, "--truth", REAL_GROUND_TRUTH_PATH, "--config", os.devnull],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "mode=on" in result.stdout
    assert "asymmetry" in result.stdout
    assert "precision=" in result.stdout and "recall=" in result.stdout and "f1=" in result.stdout


def test_cli_mode_flag_overrides_inference(tmp_path, site_dir):
    storage_dir = str(tmp_path / "storage")
    on_dir = _record(storage_dir, "episode_gt_cli2", (site_dir / "page.html").as_uri(), "auralis-on.local", "cancel_subscription")
    extract_evidence(on_dir)
    run_attributes(on_dir, storage_dir=storage_dir)

    result = subprocess.run(
        [sys.executable, os.path.join(REPO_ROOT, "validate_against_truth.py"),
         on_dir, "--truth", REAL_GROUND_TRUTH_PATH, "--mode", "off", "--config", os.devnull],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "mode=off" in result.stdout


def test_cli_fails_cleanly_on_bad_ground_truth_path(tmp_path, site_dir):
    storage_dir = str(tmp_path / "storage")
    on_dir = _record(storage_dir, "episode_gt_cli3", (site_dir / "page.html").as_uri(), "auralis-on.local", "cancel_subscription")
    extract_evidence(on_dir)
    run_attributes(on_dir, storage_dir=storage_dir)

    result = subprocess.run(
        [sys.executable, os.path.join(REPO_ROOT, "validate_against_truth.py"),
         on_dir, "--truth", str(tmp_path / "nope.yaml"), "--config", os.devnull],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "FAIL" in result.stdout
