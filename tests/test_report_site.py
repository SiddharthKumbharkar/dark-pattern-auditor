"""End-to-end test: record several real episodes across goals/revisits/
site_ids for one nominal site, run the real evidence/attribute pipeline,
then build the real site rollup report and check its actual content --
grouping by goal, links to each episode's own report, group evidence
summaries -- against genuine computed data, not mocks.
"""

import os
import subprocess
import sys

import pytest

from config.settings import Config
from journey.attribute_runner import run_attributes
from journey.evidence_extractor import extract_evidence
from journey.group_evidence_extractor import extract_group_evidence
from journey.report_site_builder import build_site_report_data, find_site_episodes
from recorder.interactive_v2 import InteractiveRecorderV2
from report_site import build_site_report

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PAGE_HTML = """<!DOCTYPE html>
<html><body><h1>Product</h1><p>Only 3 left in stock - order soon!</p></body></html>
"""


@pytest.fixture
def site_dir(tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    (site / "page.html").write_text(PAGE_HTML, encoding="utf-8")
    return site


def _record(storage_dir, episode_id, site_url, site_domain, goal_id, revisit_index=0):
    rec = InteractiveRecorderV2(
        storage_dir=storage_dir, episode_id=episode_id, site_url=site_url,
        site_domain=site_domain, sector="ecommerce", goal_id=goal_id,
        goal_description="report-site e2e test", operator="test-operator",
        config=Config(), revisit_index=revisit_index,
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
def multi_episode_storage(tmp_path, site_dir):
    storage_dir = str(tmp_path / "storage")
    url = (site_dir / "page.html").as_uri()

    signup_dir = _record(storage_dir, "episode_site_signup", url, "localhost", "complete_signup")
    cancel_dir = _record(storage_dir, "episode_site_cancel", url, "localhost", "cancel_subscription")
    pc_r0 = _record(storage_dir, "episode_site_pc_r0", url, "localhost", "purchase_cheapest", revisit_index=0)
    pc_r1 = _record(storage_dir, "episode_site_pc_r1", url, "localhost", "purchase_cheapest", revisit_index=1)
    other_site = _record(storage_dir, "episode_other_site", url, "example.com", "purchase_cheapest")

    for d in (signup_dir, cancel_dir, pc_r0, pc_r1, other_site):
        extract_evidence(d)
    extract_group_evidence("localhost", "purchase_cheapest", storage_dir)
    for d in (signup_dir, cancel_dir, pc_r0, pc_r1, other_site):
        run_attributes(d, storage_dir=storage_dir)

    return {"storage_dir": storage_dir, "dirs": {
        "signup": signup_dir, "cancel": cancel_dir, "pc_r0": pc_r0, "pc_r1": pc_r1, "other_site": other_site,
    }}


def test_find_site_episodes_filters_by_site_id_and_sorts_by_goal_then_revisit(multi_episode_storage):
    episodes = find_site_episodes("localhost", multi_episode_storage["storage_dir"])
    assert len(episodes) == 4  # not the "example.com" one
    assert all(e["site_domain"] == "localhost" for e in episodes)

    pc_episodes = [e for e in episodes if e["goal"] == "purchase_cheapest"]
    assert [e["revisit_index"] for e in pc_episodes] == [0, 1]


def test_build_site_report_data_groups_and_summarizes(multi_episode_storage):
    data = build_site_report_data("localhost", multi_episode_storage["storage_dir"])
    assert data["site_id"] == "localhost"
    assert set(data["goals"]) == {"complete_signup", "cancel_subscription", "purchase_cheapest"}
    for episode in data["episodes"]:
        assert episode["has_attributes"] is True
        assert isinstance(episode["verdict_counts"], dict)
        assert sum(episode["verdict_counts"].values()) == 7  # all 7 attributes assessed


def test_group_evidence_summary_included_for_the_revisited_goal(multi_episode_storage):
    data = build_site_report_data("localhost", multi_episode_storage["storage_dir"])
    assert len(data["group_evidence_summaries"]) == 1
    summary = data["group_evidence_summaries"][0]
    assert summary["goal"] == "purchase_cheapest"
    assert len(summary["episode_ids"]) == 2


def test_build_site_report_writes_html_and_per_episode_reports(multi_episode_storage, tmp_path):
    out_path = str(tmp_path / "rollup.html")
    data = build_site_report(
        "localhost", multi_episode_storage["storage_dir"], out_path, rebuild_episode_reports=True
    )
    assert len(data["episodes"]) == 4
    assert os.path.isfile(out_path)

    html = open(out_path, encoding="utf-8").read()
    assert "Goal: complete_signup" in html
    assert "Goal: cancel_subscription" in html
    assert "Goal: purchase_cheapest" in html
    assert "episode_site_signup" in html

    # every constituent episode's own report.html must have been built
    for episode_dir in multi_episode_storage["dirs"].values():
        if episode_dir == multi_episode_storage["dirs"]["other_site"]:
            continue
        assert os.path.isfile(os.path.join(episode_dir, "report.html"))

    # the rollup links to each episode's report via a relative path that
    # actually resolves from the rollup's own location
    rel_link = os.path.relpath(
        os.path.join(multi_episode_storage["dirs"]["signup"], "report.html"), os.path.dirname(out_path)
    )
    assert rel_link in html
    assert os.path.isfile(os.path.join(os.path.dirname(out_path), rel_link))


def test_no_rebuild_flag_skips_existing_episode_reports(multi_episode_storage, tmp_path):
    signup_report = os.path.join(multi_episode_storage["dirs"]["signup"], "report.html")
    with open(signup_report, "w", encoding="utf-8") as f:
        f.write("STALE MARKER")

    out_path = str(tmp_path / "rollup2.html")
    build_site_report(
        "localhost", multi_episode_storage["storage_dir"], out_path, rebuild_episode_reports=False
    )
    assert open(signup_report, encoding="utf-8").read() == "STALE MARKER"


def test_unknown_site_id_produces_an_empty_but_valid_report(multi_episode_storage, tmp_path):
    out_path = str(tmp_path / "empty.html")
    data = build_site_report("no-such-site", multi_episode_storage["storage_dir"], out_path)
    assert data["episodes"] == []
    html = open(out_path, encoding="utf-8").read()
    assert "No recorded episodes found" in html


# -- CLI smoke test ----------------------------------------------------


def test_cli_builds_rollup_and_reports_counts(multi_episode_storage, tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(f"output:\n  root: {multi_episode_storage['storage_dir']}\n")

    result = subprocess.run(
        [sys.executable, os.path.join(REPO_ROOT, "report_site.py"), "localhost", "--config", str(config_path)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout
    assert "4 episode(s)" in result.stdout
    assert "3 goal(s)" in result.stdout


def test_cli_warns_on_unknown_site_id(multi_episode_storage, tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(f"output:\n  root: {multi_episode_storage['storage_dir']}\n")

    result = subprocess.run(
        [sys.executable, os.path.join(REPO_ROOT, "report_site.py"), "no-such-site", "--config", str(config_path)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "WARN" in result.stdout
