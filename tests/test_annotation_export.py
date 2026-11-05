"""End-to-end test: real pipeline through evidence/attributes, then
journey/annotation_export.py's real export_for_annotation() output, plus
CLI smoke tests for export_for_annotation.py (CSV and JSON).
"""

import csv
import json
import os
import subprocess
import sys

import pytest

from attribute_agents.base import ATTRIBUTES
from config.settings import Config
from journey.annotation_export import ANNOTATION_ROW_FIELDS, export_for_annotation
from journey.attribute_runner import run_attributes
from journey.evidence_extractor import extract_evidence
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

CANCEL_HTML = """<!DOCTYPE html>
<html><body>
<h1>Manage membership</h1>
<button id="unsub-btn" type="button">Cancel my membership</button>
</body></html>
"""


@pytest.fixture
def site_dir(tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    (site / "signup.html").write_text(SIGNUP_HTML, encoding="utf-8")
    (site / "cancel.html").write_text(CANCEL_HTML, encoding="utf-8")
    return site


def _record(storage_dir, episode_id, site_url, goal_id, actions):
    rec = InteractiveRecorderV2(
        storage_dir=storage_dir, episode_id=episode_id, site_url=site_url,
        site_domain="annotate-demo.local", sector="ecommerce", goal_id=goal_id,
        goal_description="annotation export e2e test", operator="test-operator",
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
    signup_dir = _record(storage_dir, "episode_annotate_signup", (site_dir / "signup.html").as_uri(), "complete_signup", [])
    cancel_dir = _record(
        storage_dir, "episode_annotate_cancel", (site_dir / "cancel.html").as_uri(), "cancel_subscription",
        [lambda page: page.click("#unsub-btn")],
    )
    extract_evidence(signup_dir)
    extract_evidence(cancel_dir)
    run_attributes(signup_dir, storage_dir=storage_dir)
    run_attributes(cancel_dir, storage_dir=storage_dir)
    return {"storage_dir": storage_dir, "signup_dir": signup_dir, "cancel_dir": cancel_dir}


def test_one_row_per_episode_per_attribute(pipeline):
    rows = export_for_annotation([pipeline["signup_dir"], pipeline["cancel_dir"]], pipeline["storage_dir"])
    assert len(rows) == 2 * len(ATTRIBUTES)
    signup_rows = [r for r in rows if r["episode_id"] == "episode_annotate_signup"]
    cancel_rows = [r for r in rows if r["episode_id"] == "episode_annotate_cancel"]
    assert sorted(r["attribute"] for r in signup_rows) == sorted(ATTRIBUTES)
    assert sorted(r["attribute"] for r in cancel_rows) == sorted(ATTRIBUTES)


def test_row_shape_and_empty_human_columns(pipeline):
    rows = export_for_annotation([pipeline["signup_dir"]], pipeline["storage_dir"])
    for row in rows:
        assert set(row.keys()) == set(ANNOTATION_ROW_FIELDS)
        assert row["human_verdict"] == ""
        assert row["annotator_id"] == ""
        assert isinstance(row["evidence_summary"], dict)
        assert "relevant_evidence" in row["evidence_summary"]


def test_evidence_summary_is_scoped_per_attribute_not_the_full_episode(pipeline):
    rows = export_for_annotation([pipeline["signup_dir"]], pipeline["storage_dir"])
    asymmetry_row = next(r for r in rows if r["attribute"] == "asymmetry")
    complexity_row = next(r for r in rows if r["attribute"] == "complexity")
    assert "visual_asymmetry" in asymmetry_row["evidence_summary"]["relevant_evidence"]
    assert "complexity_metrics" not in asymmetry_row["evidence_summary"]["relevant_evidence"]
    assert "complexity_metrics" in complexity_row["evidence_summary"]["relevant_evidence"]
    assert "visual_asymmetry" not in complexity_row["evidence_summary"]["relevant_evidence"]


def test_code_verdict_matches_the_real_stored_attribute_result(pipeline):
    from journey.schema_migration import load_episode
    episode = load_episode(os.path.join(pipeline["signup_dir"], "episode.json"))
    code_by_attr = {r["attribute"]: r for r in episode["attributes"]["results"]}

    rows = export_for_annotation([pipeline["signup_dir"]], pipeline["storage_dir"])
    for row in rows:
        code = code_by_attr[row["attribute"]]
        assert row["code_verdict"] == code["verdict"]
        assert row["code_severity"] == code["severity"]
        assert row["code_reasoning"] == code["reasoning"]


def test_cli_writes_csv_with_one_row_per_episode_attribute(pipeline, tmp_path):
    out_path = str(tmp_path / "labels.csv")
    result = subprocess.run(
        [sys.executable, os.path.join(REPO_ROOT, "export_for_annotation.py"),
         pipeline["signup_dir"], pipeline["cancel_dir"], "--out", out_path],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout

    with open(out_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2 * len(ATTRIBUTES)
    assert set(rows[0].keys()) == set(ANNOTATION_ROW_FIELDS)
    # evidence_summary must round-trip as embedded JSON text in the CSV cell.
    parsed = json.loads(rows[0]["evidence_summary"])
    assert "relevant_evidence" in parsed
    assert rows[0]["human_verdict"] == ""
    assert rows[0]["annotator_id"] == ""


def test_cli_writes_json_when_format_flag_given(pipeline, tmp_path):
    out_path = str(tmp_path / "labels.json")
    result = subprocess.run(
        [sys.executable, os.path.join(REPO_ROOT, "export_for_annotation.py"),
         pipeline["signup_dir"], "--format", "json", "--out", out_path],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    rows = json.load(open(out_path, encoding="utf-8"))
    assert len(rows) == len(ATTRIBUTES)
    assert isinstance(rows[0]["evidence_summary"], dict)  # native JSON, not double-encoded
