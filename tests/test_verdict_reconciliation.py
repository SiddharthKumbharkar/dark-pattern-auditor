"""End-to-end test: real pipeline through evidence/attributes/ingest, then
journey/verdict_reconciliation.py's real compare_verdicts() output, plus
CLI smoke tests for compare_verdicts.py.
"""

import json
import os
import subprocess
import sys

import pytest

from attribute_agents.base import ATTRIBUTES
from config.settings import Config
from journey.attribute_runner import run_attributes
from journey.evidence_extractor import extract_evidence
from journey.mechanism_verdict_ingest import ingest_response
from journey.schema_migration import load_episode
from journey.verdict_reconciliation import compare_verdicts
from llm.payload_builder import build_payload
from recorder.interactive_v2 import InteractiveRecorderV2

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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
    (site / "signup.html").write_text(SIGNUP_HTML, encoding="utf-8")
    return site


def _record(storage_dir, episode_id, site_url, goal_id, actions):
    rec = InteractiveRecorderV2(
        storage_dir=storage_dir, episode_id=episode_id, site_url=site_url,
        site_domain="reconcile-demo.local", sector="ecommerce", goal_id=goal_id,
        goal_description="reconciliation e2e test", operator="test-operator",
        config=Config(), paired_episode_id=None,
    )
    page = rec.launch(headless=True)
    try:
        rec._poll_tick()
        for act in actions:
            act(page)
            rec._poll_tick()
    finally:
        rec._teardown_browser()
        rec._cleanup_raw_artifacts()
    rec.finalize()
    return rec.episode_dir


@pytest.fixture
def pipeline(tmp_path, site_dir):
    storage_dir = str(tmp_path / "storage")
    signup_dir = _record(storage_dir, "episode_reconcile_signup", (site_dir / "signup.html").as_uri(), "complete_signup", [])
    extract_evidence(signup_dir)
    run_attributes(signup_dir, storage_dir=storage_dir)

    payload_root = str(tmp_path / "payload")
    build_payload(signup_dir, role="attribute", attribute="asymmetry", storage_dir=storage_dir, payload_root=payload_root)
    build_payload(signup_dir, role="attribute", attribute="covertness", storage_dir=storage_dir, payload_root=payload_root)

    return {"storage_dir": storage_dir, "payload_root": payload_root, "signup_dir": signup_dir}


def _write(tmp_path, name, obj):
    path = os.path.join(str(tmp_path), name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    return path


def test_all_seven_attributes_present_even_with_no_llm_data(pipeline):
    episode = load_episode(os.path.join(pipeline["signup_dir"], "episode.json"))
    rows = compare_verdicts(episode)
    assert [r["attribute"] for r in rows] == list(ATTRIBUTES)
    for row in rows:
        assert row["code_verdict"] is not None  # run-attributes always assesses all 7
        assert row["llm_verdict"] is None
        assert row["agree"] is None
        assert "no LLM verdict yet" in row["notes"]


def test_agreement_and_disagreement_after_ingesting_two_attributes(pipeline, tmp_path):
    # asymmetry: code fired (per fixture) -- agree by matching it exactly.
    episode_before = load_episode(os.path.join(pipeline["signup_dir"], "episode.json"))
    code_asymmetry = next(r for r in episode_before["attributes"]["results"] if r["attribute"] == "asymmetry")
    assert code_asymmetry["verdict"] == "fires"

    agree_path = _write(tmp_path, "agree.json", {
        "attribute": "asymmetry", "verdict": "fires", "severity": code_asymmetry["severity"], "confidence": 0.9,
        "evidence_pointers": [{"step_id": 1, "selector": "#accept-btn", "ui_region": "account_settings", "signal": "measured_contrast"}],
        "reasoning": "Agrees with the code agent.",
    })
    # covertness: code is always not_assessable (stub) -- LLM disagrees with "fires".
    disagree_path = _write(tmp_path, "disagree.json", {
        "attribute": "covertness", "verdict": "fires", "severity": 2, "confidence": 0.6,
        "evidence_pointers": [{"step_id": 1, "selector": "#reject-btn", "ui_region": "account_settings", "signal": "measured_contrast"}],
        "reasoning": "Reject option is measurably harder to notice.",
    })

    ingest_response(pipeline["signup_dir"], role="attribute", response_file=agree_path,
                     model_name="m", operator="sid", storage_dir=pipeline["storage_dir"], payload_root=pipeline["payload_root"])
    ingest_response(pipeline["signup_dir"], role="attribute", response_file=disagree_path,
                     model_name="m", operator="sid", storage_dir=pipeline["storage_dir"], payload_root=pipeline["payload_root"])

    episode = load_episode(os.path.join(pipeline["signup_dir"], "episode.json"))
    rows = {r["attribute"]: r for r in compare_verdicts(episode)}

    assert rows["asymmetry"]["agree"] is True
    assert rows["asymmetry"]["llm_verdict"] == "fires"

    assert rows["covertness"]["agree"] is False
    assert rows["covertness"]["code_verdict"] == "not_assessable"
    assert rows["covertness"]["llm_verdict"] == "fires"
    assert "not_assessable" in rows["covertness"]["notes"]
    assert "fires" in rows["covertness"]["notes"]

    # attributes never ingested still show as missing-data, not disagreement.
    assert rows["complexity"]["llm_verdict"] is None
    assert rows["complexity"]["agree"] is None


def test_agreeing_verdicts_with_different_severity_are_still_agree_but_noted(pipeline, tmp_path):
    episode_before = load_episode(os.path.join(pipeline["signup_dir"], "episode.json"))
    code_asymmetry = next(r for r in episode_before["attributes"]["results"] if r["attribute"] == "asymmetry")
    different_severity = 1 if code_asymmetry["severity"] != 1 else 2

    response_path = _write(tmp_path, "resp.json", {
        "attribute": "asymmetry", "verdict": "fires", "severity": different_severity, "confidence": 0.9,
        "evidence_pointers": [{"step_id": 1, "selector": "#accept-btn", "ui_region": "account_settings", "signal": "measured_contrast"}],
        "reasoning": "Agrees on verdict, differs on severity.",
    })
    ingest_response(pipeline["signup_dir"], role="attribute", response_file=response_path,
                     model_name="m", operator="sid", storage_dir=pipeline["storage_dir"], payload_root=pipeline["payload_root"])

    episode = load_episode(os.path.join(pipeline["signup_dir"], "episode.json"))
    row = next(r for r in compare_verdicts(episode) if r["attribute"] == "asymmetry")
    assert row["agree"] is True
    assert "severity differs" in row["notes"]


def test_cli_prints_table_and_disagreements_section(pipeline, tmp_path):
    disagree_path = _write(tmp_path, "disagree.json", {
        "attribute": "covertness", "verdict": "fires", "severity": 2, "confidence": 0.6,
        "evidence_pointers": [{"step_id": 1, "selector": "#reject-btn", "ui_region": "account_settings", "signal": "x"}],
        "reasoning": "Measurably harder to notice.",
    })
    ingest_response(pipeline["signup_dir"], role="attribute", response_file=disagree_path,
                     model_name="m", operator="sid", storage_dir=pipeline["storage_dir"], payload_root=pipeline["payload_root"])

    result = subprocess.run(
        [sys.executable, os.path.join(REPO_ROOT, "compare_verdicts.py"), pipeline["signup_dir"]],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "attribute" in result.stdout and "code_verdict" in result.stdout and "llm_verdict" in result.stdout
    assert "Disagreements (1)" in result.stdout
    assert "covertness" in result.stdout


def test_cli_reports_no_disagreements_when_nothing_ingested(pipeline):
    result = subprocess.run(
        [sys.executable, os.path.join(REPO_ROOT, "compare_verdicts.py"), pipeline["signup_dir"]],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "No disagreements." in result.stdout
