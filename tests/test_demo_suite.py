"""Tests for journey/demo_suite.py and run_demo_suite.py: required-session
computation, the resumable progress file, candidate-episode detection, and
the full process_confirmed_sessions -> report -> suite_passed pipeline --
run against REAL recorded episodes (headless Playwright), not mocks.
CLI wizard behavior is exercised via subprocess with scripted stdin.
"""

import os
import subprocess
import sys

import pytest

from config.settings import Config
from journey.demo_suite import (
    REACHABLE_GOALS,
    candidate_episodes,
    format_report,
    load_progress,
    process_confirmed_sessions,
    required_sessions,
    save_progress,
    session_key,
    suite_passed,
)
from journey.ground_truth import load_ground_truth
from recorder.interactive_v2 import InteractiveRecorderV2

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL_GROUND_TRUTH_PATH = os.path.join(REPO_ROOT, "ground_truth.yaml")

SIGNUP_HTML = """<!DOCTYPE html>
<html><body>
<h1>Create your account</h1>
<button id="accept-btn" type="button"
  style="background:#000;color:#fff;font-size:20px;padding:14px;">Yes, sign me up</button>
<button id="reject-btn" type="button"
  style="background:#f5f5f5;color:#f0f0f0;font-size:8px;padding:2px;">No thanks</button>
</body></html>
"""

CLEAN_HTML = """<!DOCTYPE html>
<html><body>
<h1>Manage membership</h1>
<button id="cancel-btn" type="button">Cancel membership</button>
</body></html>
"""


@pytest.fixture
def ground_truth():
    return load_ground_truth(REAL_GROUND_TRUTH_PATH)


@pytest.fixture
def site_dir(tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    (site / "asymmetric.html").write_text(SIGNUP_HTML, encoding="utf-8")
    (site / "clean.html").write_text(CLEAN_HTML, encoding="utf-8")
    return site


def _record(storage_dir, episode_id, site_url, site_domain, goal_id, revisit_index=0, paired_episode_id=None):
    rec = InteractiveRecorderV2(
        storage_dir=storage_dir, episode_id=episode_id, site_url=site_url,
        site_domain=site_domain, sector="ecommerce", goal_id=goal_id,
        goal_description="demo suite e2e test", operator="test-operator",
        config=Config(), revisit_index=revisit_index, paired_episode_id=paired_episode_id,
    )
    rec.launch(headless=True)
    try:
        rec._poll_tick()
    finally:
        rec._teardown_browser()
        rec._cleanup_raw_artifacts()
    rec.finalize()
    return rec.episode_dir


# -- required_sessions ---------------------------------------------------


def test_required_sessions_covers_every_reachable_goal_on_and_off(ground_truth):
    sessions = required_sessions(ground_truth, [24, 72])
    keys = {s["session_key"] for s in sessions}
    for goal in REACHABLE_GOALS:
        assert session_key(goal, "on", 0) in keys
        assert session_key(goal, "off", 0) in keys


def test_required_sessions_adds_extra_revisits_only_for_revisit_dependent_goals(ground_truth):
    sessions = required_sessions(ground_truth, [24, 72])
    revisit_sessions = [s for s in sessions if s["revisit_index"] > 0]
    assert {s["goal"] for s in revisit_sessions} == {"purchase_cheapest"}
    assert len(revisit_sessions) == 2  # one per offset in [24, 72]


def test_required_sessions_pairs_on_and_off_of_the_same_goal(ground_truth):
    sessions = {s["session_key"]: s for s in required_sessions(ground_truth, [24, 72])}
    on_key = session_key("cancel_subscription", "on", 0)
    off_key = session_key("cancel_subscription", "off", 0)
    # Only ON declares pair_with (referencing OFF's episode_id, known by
    # the time ON is recorded); OFF is recorded first and can't forward-
    # reference an episode_id that doesn't exist yet -- see
    # journey/demo_suite.py's required_sessions() docstring.
    assert sessions[on_key]["pair_with"] == off_key
    assert sessions[off_key]["pair_with"] is None


def test_extra_revisit_sessions_are_not_paired(ground_truth):
    sessions = {s["session_key"]: s for s in required_sessions(ground_truth, [24, 72])}
    assert sessions[session_key("purchase_cheapest", "on", 1)]["pair_with"] is None


def test_off_session_is_always_listed_before_its_paired_on_session(ground_truth):
    # record.py generates episode_ids itself (timestamp-based) -- the ON
    # session's --pair-with can only reference a REAL episode_id if OFF
    # was recorded (and its episode_id known) first. If this ordering
    # ever regresses, the wizard would print an unfillable placeholder.
    sessions = required_sessions(ground_truth, [24, 72])
    order = [s["session_key"] for s in sessions]
    for goal in REACHABLE_GOALS:
        off_index = order.index(session_key(goal, "off", 0))
        on_index = order.index(session_key(goal, "on", 0))
        assert off_index < on_index, f"{goal}: off must be recorded before its paired on session"


def test_revisit_count_follows_config_offsets(ground_truth):
    sessions = required_sessions(ground_truth, [24, 48, 72])
    # purchase_cheapest has an (on, r0) AND an (off, r0) session -- hence
    # two 0s -- plus one extra "on" revisit per configured offset (3 here).
    revisit_indices = sorted(s["revisit_index"] for s in sessions if s["goal"] == "purchase_cheapest")
    assert revisit_indices == [0, 0, 1, 2, 3]


# -- progress file ---------------------------------------------------


def test_progress_round_trips(tmp_path):
    storage_dir = str(tmp_path / "storage")
    assert load_progress(storage_dir) == {}
    progress = {"k": {"episode_id": "e1"}}
    save_progress(storage_dir, progress)
    assert load_progress(storage_dir) == progress


# -- candidate_episodes ---------------------------------------------------


def test_candidate_episodes_matches_by_site_domain_goal_and_revisit_index(tmp_path, site_dir):
    storage_dir = str(tmp_path / "storage")
    _record(storage_dir, "ep_a", (site_dir / "clean.html").as_uri(), "auralis-on.local", "purchase_cheapest", revisit_index=0)
    _record(storage_dir, "ep_b", (site_dir / "clean.html").as_uri(), "auralis-off.local", "purchase_cheapest", revisit_index=0)
    _record(storage_dir, "ep_c", (site_dir / "clean.html").as_uri(), "auralis-on.local", "purchase_cheapest", revisit_index=1)

    matches = candidate_episodes(storage_dir, "auralis-on.local", "purchase_cheapest", 0)
    assert [m["episode_id"] for m in matches] == ["ep_a"]


def test_candidate_episodes_newest_first(tmp_path, site_dir):
    storage_dir = str(tmp_path / "storage")
    _record(storage_dir, "ep_first", (site_dir / "clean.html").as_uri(), "auralis-on.local", "purchase_cheapest", revisit_index=0)
    _record(storage_dir, "ep_second", (site_dir / "clean.html").as_uri(), "auralis-on.local", "purchase_cheapest", revisit_index=0)
    matches = candidate_episodes(storage_dir, "auralis-on.local", "purchase_cheapest", 0)
    assert matches[0]["episode_id"] == "ep_second"


def test_candidate_episodes_empty_when_nothing_matches(tmp_path):
    assert candidate_episodes(str(tmp_path / "nope"), "auralis-on.local", "purchase_cheapest", 0) == []


# -- process_confirmed_sessions / report / suite_passed (real pipeline) --


def _confirm(progress, storage_dir, session, episode_id):
    progress[session["session_key"]] = {
        "session_key": session["session_key"], "episode_id": episode_id, "goal": session["goal"],
        "mode": session["mode"], "revisit_index": session["revisit_index"], "site_domain": session["site_domain"],
    }
    save_progress(storage_dir, progress)


def test_full_pipeline_clean_off_run_passes(tmp_path, site_dir, ground_truth):
    storage_dir = str(tmp_path / "storage")
    sessions = {s["session_key"]: s for s in required_sessions(ground_truth, [24, 72])}
    progress = {}

    # Only record the cancel_subscription pair for this test -- asymmetric
    # markup ON (genuinely fires asymmetry/restriction-relevant evidence),
    # clean markup OFF (nothing should fire).
    on_session = sessions[session_key("cancel_subscription", "on", 0)]
    off_session = sessions[session_key("cancel_subscription", "off", 0)]

    on_id = "episode_suite_cancel_on"
    off_id = "episode_suite_cancel_off"
    _record(storage_dir, on_id, (site_dir / "asymmetric.html").as_uri(), "auralis-on.local", "cancel_subscription",
            paired_episode_id=off_id)
    _record(storage_dir, off_id, (site_dir / "clean.html").as_uri(), "auralis-off.local", "cancel_subscription",
            paired_episode_id=on_id)

    _confirm(progress, storage_dir, on_session, on_id)
    _confirm(progress, storage_dir, off_session, off_id)

    report = process_confirmed_sessions(progress, ground_truth, storage_dir)

    assert len(report["on_results"]) == 1
    assert len(report["off_results"]) == 1
    assert report["false_positives"] == []
    assert suite_passed(report) is True

    on_row = next(r for r in report["on_results"][0]["rows"] if r["attribute"] == "asymmetry")
    assert on_row["classification"] == "TP"  # the asymmetric fixture genuinely fires it

    text = format_report(report)
    assert "SUITE PASSED" in text
    assert "DETECTED" in text and "asymmetry" in text


def test_full_pipeline_off_run_with_false_positive_fails_the_suite(tmp_path, site_dir, ground_truth):
    storage_dir = str(tmp_path / "storage")
    sessions = {s["session_key"]: s for s in required_sessions(ground_truth, [24, 72])}
    progress = {}

    on_session = sessions[session_key("cancel_subscription", "on", 0)]
    off_session = sessions[session_key("cancel_subscription", "off", 0)]

    on_id = "episode_suite_fp_on"
    off_id = "episode_suite_fp_off"
    # Deliberately give the OFF episode the SAME asymmetric markup as ON --
    # simulating an operator mistake (forgot to toggle patterns off) or a
    # genuine pipeline bug -- either way this must fail the suite loudly.
    _record(storage_dir, on_id, (site_dir / "asymmetric.html").as_uri(), "auralis-on.local", "cancel_subscription",
            paired_episode_id=off_id)
    _record(storage_dir, off_id, (site_dir / "asymmetric.html").as_uri(), "auralis-off.local", "cancel_subscription",
            paired_episode_id=on_id)

    _confirm(progress, storage_dir, on_session, on_id)
    _confirm(progress, storage_dir, off_session, off_id)

    report = process_confirmed_sessions(progress, ground_truth, storage_dir)

    assert suite_passed(report) is False
    assert len(report["false_positives"]) >= 1
    assert any(fp["attribute"] == "asymmetry" for fp in report["false_positives"])

    text = format_report(report)
    assert "SUITE FAILED" in text
    assert "FALSE POSITIVE" in text


def test_revisit_section_reflects_claim_persistence_from_the_on_group(tmp_path, site_dir, ground_truth):
    # purchase_cheapest needs 3 ON revisits (r0/r1/r2) for its
    # revisit-dependent patterns -- give each a "3 left in stock"-style
    # claim that stays identical across revisits (a plausible-looking
    # but, per signals/claim_persistence.py's rules, checkable claim).
    STOCK_HTML = """<!DOCTYPE html>
    <html><body><h1>Product</h1><p>Only 3 left in stock - order soon!</p></body></html>
    """
    site = tmp_path / "stock_site"
    site.mkdir()
    (site / "product.html").write_text(STOCK_HTML, encoding="utf-8")

    storage_dir = str(tmp_path / "storage")
    sessions = {s["session_key"]: s for s in required_sessions(ground_truth, [24, 72])}
    progress = {}

    episode_ids = {}
    for revisit_index in (0, 1, 2):
        key = session_key("purchase_cheapest", "on", revisit_index)
        episode_id = f"episode_suite_revisit_r{revisit_index}"
        _record(storage_dir, episode_id, (site / "product.html").as_uri(), "auralis-on.local", "purchase_cheapest",
                revisit_index=revisit_index)
        episode_ids[revisit_index] = episode_id
        _confirm(progress, storage_dir, sessions[key], episode_id)

    off_key = session_key("purchase_cheapest", "off", 0)
    off_id = "episode_suite_revisit_off"
    _record(storage_dir, off_id, (site / "product.html").as_uri(), "auralis-off.local", "purchase_cheapest")
    _confirm(progress, storage_dir, sessions[off_key], off_id)

    report = process_confirmed_sessions(progress, ground_truth, storage_dir)

    assert len(report["revisit_section"]) == 1
    section = report["revisit_section"][0]
    assert section["goal"] == "purchase_cheapest"
    assert isinstance(section["claim_persistence"], list)

    text = format_report(report)
    assert "claim_persistence" in text or "(no claim_persistence" in text


# -- CLI wizard (subprocess, scripted stdin) ------------------------------


def test_cli_prints_pending_sessions_and_exits_zero_when_nothing_confirmed(tmp_path):
    storage_dir = str(tmp_path / "storage")
    os.makedirs(storage_dir, exist_ok=True)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(f"output:\n  root: {storage_dir}\n")

    # Answer "skip" to every prompt -- 10 required sessions.
    scripted_input = "skip\n" * 10

    result = subprocess.run(
        [sys.executable, os.path.join(REPO_ROOT, "run_demo_suite.py"),
         "--truth", REAL_GROUND_TRUTH_PATH, "--config", str(config_path)],
        input=scripted_input, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "sessions confirmed" in result.stdout
    assert "purchase_cheapest__on__r0" in result.stdout


def test_cli_wizard_pairs_on_session_with_the_real_off_episode_id(tmp_path, site_dir):
    # First required session is purchase_cheapest OFF (r0); confirm it
    # with a real recorded episode_id. The very next printed session
    # (purchase_cheapest ON, r0) must reference that REAL episode_id in
    # its --pair-with flag, not an unfillable placeholder -- this is the
    # ordering fix in journey/demo_suite.py's required_sessions().
    storage_dir = str(tmp_path / "storage")
    os.makedirs(storage_dir, exist_ok=True)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(f"output:\n  root: {storage_dir}\n")

    off_id = "episode_wizard_pair_off"
    _record(storage_dir, off_id, (site_dir / "clean.html").as_uri(), "auralis-off.local", "purchase_cheapest")

    # Answers: real episode_id for session 1 (pc off r0), then "skip" for
    # the remaining 9 sessions.
    scripted_input = off_id + "\n" + "skip\n" * 9

    result = subprocess.run(
        [sys.executable, os.path.join(REPO_ROOT, "run_demo_suite.py"),
         "--truth", REAL_GROUND_TRUTH_PATH, "--config", str(config_path)],
        input=scripted_input, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert f"Confirmed: purchase_cheapest__off__r0 -> {off_id}" in result.stdout
    assert f"--pair-with {off_id}" in result.stdout
    assert "--pair-with <episode_id of" not in result.stdout  # the old, unfillable placeholder form


def test_cli_runs_processing_phase_when_progress_file_is_already_complete(tmp_path, site_dir, ground_truth):
    storage_dir = str(tmp_path / "storage")
    os.makedirs(storage_dir, exist_ok=True)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(f"output:\n  root: {storage_dir}\n")

    sessions = required_sessions(ground_truth, [24, 72])
    progress = {}
    for s in sessions:
        # Every session gets the SAME clean page -- OFF sessions are truly
        # clean by construction; ON sessions being "clean" too just means
        # the ON run will show missed detections (not a suite failure).
        site_url = (site_dir / "clean.html").as_uri()
        episode_id = f"episode_{s['session_key']}"
        _record(storage_dir, episode_id, site_url, s["site_domain"], s["goal"], revisit_index=s["revisit_index"])
        _confirm(progress, storage_dir, s, episode_id)

    result = subprocess.run(
        [sys.executable, os.path.join(REPO_ROOT, "run_demo_suite.py"),
         "--truth", REAL_GROUND_TRUTH_PATH, "--config", str(config_path)],
        input="", capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr  # clean pages everywhere -> no false positives -> suite passes
    assert "AURALIS DEMO SUITE REPORT" in result.stdout
    assert "SUITE PASSED" in result.stdout
