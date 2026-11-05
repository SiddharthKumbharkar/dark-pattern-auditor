"""End-to-end test: record a real episode with a genuine asymmetric
button pair, run the real evidence/attribute pipeline, then build the
real HTML report and check its actual content -- bounding boxes,
screenshot embedding, evidence tables, attribute cards -- against known
fixture values, not mocks.
"""

import os
import re
import subprocess
import sys

import pytest

from config.settings import Config
from journey.attribute_runner import run_attributes
from journey.evidence_extractor import extract_evidence
from journey.report_builder import build_report_data
from journey.report_html import render_html
from journey.schema_migration import load_episode
from recorder.interactive_v2 import InteractiveRecorderV2
from report import build_episode_report

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


def _record(storage_dir, episode_id, site_url, goal_id="complete_signup"):
    rec = InteractiveRecorderV2(
        storage_dir=storage_dir, episode_id=episode_id, site_url=site_url,
        site_domain="localhost", sector="ecommerce", goal_id=goal_id,
        goal_description="report e2e test", operator="test-operator", config=Config(),
    )
    rec.launch(headless=True)
    try:
        rec._poll_tick()
    finally:
        rec._teardown_browser()
        rec._cleanup_raw_artifacts()
    rec.finalize()
    return rec.episode_dir


@pytest.fixture
def processed_episode_dir(tmp_path, site_dir):
    storage_dir = str(tmp_path / "storage")
    episode_dir = _record(storage_dir, "episode_report_e2e", (site_dir / "signup.html").as_uri())
    extract_evidence(episode_dir)
    run_attributes(episode_dir, storage_dir=storage_dir)
    return episode_dir


def test_report_data_resolves_a_real_bounding_box_for_a_firing_pointer(processed_episode_dir):
    episode = load_episode(os.path.join(processed_episode_dir, "episode.json"))
    data = build_report_data(episode, processed_episode_dir)

    asymmetry = next(s for s in data["attribute_sections"] if s["attribute"] == "asymmetry")
    assert asymmetry["verdict"] == "fires"
    assert asymmetry["resolved_pointers"]
    for pointer in asymmetry["resolved_pointers"]:
        assert pointer["bounding_box"] is not None
        for key in ("x", "y", "width", "height"):
            assert isinstance(pointer["bounding_box"][key], (int, float))


def test_filmstrip_step_carries_merged_boxes_and_screenshot(processed_episode_dir):
    episode = load_episode(os.path.join(processed_episode_dir, "episode.json"))
    data = build_report_data(episode, processed_episode_dir)

    step = data["filmstrip"][0]
    assert step["screenshot_b64"]
    assert step["image_width"] and step["image_height"]
    assert len(step["boxes"]) == 2  # accept-btn and reject-btn, deduped per selector
    # each box's percentages must be within [0, 100] -- a genuine sanity
    # check on the pixel->percent conversion, not just "some number exists"
    for box in step["boxes"]:
        bb = box["bounding_box"]
        assert 0 <= bb["x"] <= step["image_width"]
        assert 0 <= bb["y"] <= step["image_height"]
        assert bb["width"] > 0 and bb["height"] > 0


def test_evidence_pointers_at_the_same_selector_merge_into_one_box_with_combined_labels(processed_episode_dir):
    episode = load_episode(os.path.join(processed_episode_dir, "episode.json"))
    data = build_report_data(episode, processed_episode_dir)
    step = data["filmstrip"][0]
    accept_box = next(b for b in step["boxes"] if b["bounding_box"]["x"] < 700)  # accept button is the left/first one
    assert len(accept_box["labels"]) >= 2  # e.g. contrast_ratio AND area_ratio both point at #accept-btn


def test_html_contains_embedded_screenshot_bbox_overlay_and_attribute_card(processed_episode_dir):
    episode = load_episode(os.path.join(processed_episode_dir, "episode.json"))
    data = build_report_data(episode, processed_episode_dir)
    html = render_html(data)

    assert "data:image/png;base64," in html
    assert 'class="bbox fires"' in html
    assert 'id="step-1"' in html
    assert 'class="attribute-card"' in html
    assert "asymmetry" in html
    # a link from the attribute card to the filmstrip anchor
    assert re.search(r'<a href="#step-1">Step 1</a>', html)


def test_html_escapes_evidence_derived_text(tmp_path, site_dir):
    # A page whose visible text contains characters that would break raw
    # HTML insertion -- the report must escape them, not inject them.
    hostile_html = """<!DOCTYPE html>
    <html><body>
    <h1>Create your account</h1>
    <button id="accept-btn" style="background:#000;color:#fff;font-size:20px;">Yes &lt;script&gt;</button>
    <button id="reject-btn" style="background:#eee;color:#eee;font-size:6px;">No" onclick="alert(1)</button>
    </body></html>
    """
    (site_dir / "hostile.html").write_text(hostile_html, encoding="utf-8")
    storage_dir = str(tmp_path / "storage")
    episode_dir = _record(storage_dir, "episode_report_hostile", (site_dir / "hostile.html").as_uri())
    extract_evidence(episode_dir)
    run_attributes(episode_dir, storage_dir=storage_dir)

    episode = load_episode(os.path.join(episode_dir, "episode.json"))
    data = build_report_data(episode, episode_dir)
    html = render_html(data)
    assert "<script>" not in html
    assert 'onclick="alert(1)' not in html


def test_report_with_no_evidence_or_attributes_yet_renders_placeholders(tmp_path, site_dir):
    storage_dir = str(tmp_path / "storage")
    episode_dir = _record(storage_dir, "episode_report_bare", (site_dir / "signup.html").as_uri())
    episode = load_episode(os.path.join(episode_dir, "episode.json"))
    data = build_report_data(episode, episode_dir)
    html = render_html(data)
    assert "run extract-evidence" in html
    assert "run run-attributes" in html
    assert "run build-payload / ingest-response" in html


def test_build_episode_report_writes_html_file_by_default_alongside_episode(processed_episode_dir):
    out_path = build_episode_report(processed_episode_dir)
    assert out_path == os.path.join(processed_episode_dir, "report.html")
    assert os.path.isfile(out_path)
    assert "<html" in open(out_path, encoding="utf-8").read()


def test_build_episode_report_respects_explicit_out_path(processed_episode_dir, tmp_path):
    out_path = str(tmp_path / "custom" / "my_report.html")
    result = build_episode_report(processed_episode_dir, out_path=out_path)
    assert result == out_path
    assert os.path.isfile(out_path)


# -- CLI smoke test ----------------------------------------------------


def test_cli_builds_report_and_prints_path(processed_episode_dir):
    result = subprocess.run(
        [sys.executable, os.path.join(REPO_ROOT, "report.py"), processed_episode_dir],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout
    assert os.path.isfile(os.path.join(processed_episode_dir, "report.html"))
