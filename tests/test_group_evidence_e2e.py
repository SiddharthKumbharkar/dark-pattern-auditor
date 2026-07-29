"""End-to-end test: record three real episodes (revisit_index 0/1/2) of
the same (site_id, goal), each against a real local HTML page with
slightly different content (stock/timer/viewer text, simulating what a
site would actually show across visits), run the real single-episode
extractor on each, then the real group extractor -- and check the
resulting group_evidence.json against genuine computed values.

Real Playwright recording happens in seconds, not days, so after each
recording the resulting episode.json's timestamps are patched to a
realistic multi-day spacing -- everything else (masking, claim
extraction, computed styles) is the real, unmodified pipeline.
"""

import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from config.settings import Config
from journey.baselines import BaselineStore
from journey.group_evidence_extractor import extract_group_evidence, group_id_for
from journey.schema_migration import validate_group_evidence, validate_v2
from recorder.interactive_v2 import InteractiveRecorderV2

SITE_ID = "auralis-demo.local"
GOAL = "purchase_cheapest"

PAGE_TEMPLATE = """<!DOCTYPE html>
<html><body>
<h1>Auralis Pro X</h1>
<p>Only {stock} left in stock!</p>
<p>Ends in {timer}. {viewers} people are viewing this.</p>
<p>Price: Rs. 8999</p>
</body></html>
"""


@pytest.fixture
def site_dir(tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    (site / "revisit0.html").write_text(
        PAGE_TEMPLATE.format(stock=10, timer="02:00:00", viewers=40), encoding="utf-8"
    )
    (site / "revisit1.html").write_text(
        PAGE_TEMPLATE.format(stock=6, timer="02:00:00", viewers=40), encoding="utf-8"
    )
    (site / "revisit2.html").write_text(
        PAGE_TEMPLATE.format(stock=2, timer="02:00:00", viewers=40), encoding="utf-8"
    )
    return site


def _record_revisit(storage_dir, site_dir, revisit_index, page_name):
    episode_id = f"episode_group_e2e_r{revisit_index}"
    rec = InteractiveRecorderV2(
        storage_dir=storage_dir,
        episode_id=episode_id,
        site_url=(site_dir / page_name).as_uri(),
        site_domain=SITE_ID,
        sector="ecommerce",
        goal_id=GOAL,
        goal_description="group evidence e2e test",
        operator="test-operator",
        config=Config(),
        revisit_index=revisit_index,
    )
    rec.launch(headless=True)
    try:
        rec._poll_tick()
    finally:
        rec._teardown_browser()
        rec._cleanup_raw_artifacts()
    rec.finalize()
    return episode_id, rec.episode_dir


def _shift_episode_timestamps(episode_dir, new_start: datetime):
    episode_path = os.path.join(episode_dir, "episode.json")
    with open(episode_path, "r", encoding="utf-8") as f:
        episode = json.load(f)

    old_start = datetime.fromisoformat(episode["audit_metadata"]["audit_start_time"])
    delta = new_start - old_start

    def shift(iso):
        return (datetime.fromisoformat(iso) + delta).isoformat()

    episode["audit_metadata"]["audit_start_time"] = shift(episode["audit_metadata"]["audit_start_time"])
    if episode["audit_metadata"]["audit_end_time"]:
        episode["audit_metadata"]["audit_end_time"] = shift(episode["audit_metadata"]["audit_end_time"])
    for step in episode["steps"]:
        step["timestamp"] = shift(step["timestamp"])

    with open(episode_path, "w", encoding="utf-8") as f:
        json.dump(episode, f, indent=2)


@pytest.fixture
def baselines_path(tmp_path):
    path = os.path.join(str(tmp_path), "baselines.json")
    store = BaselineStore(path=path)
    store.save()  # writes the seed values to this isolated test path
    return path


def test_claim_persistence_and_group_evidence_across_three_revisits(tmp_path, site_dir, baselines_path):
    storage_dir = str(tmp_path / "storage")

    day0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    revisits = [
        (0, "revisit0.html", day0),
        (1, "revisit1.html", day0 + timedelta(days=1)),
        (2, "revisit2.html", day0 + timedelta(days=3)),
    ]

    episode_ids = []
    for revisit_index, page_name, when in revisits:
        episode_id, episode_dir = _record_revisit(storage_dir, site_dir, revisit_index, page_name)
        _shift_episode_timestamps(episode_dir, when)
        episode_ids.append(episode_id)

    group_evidence = extract_group_evidence(SITE_ID, GOAL, storage_dir, baselines_path=baselines_path)

    assert validate_group_evidence(group_evidence) == []
    assert group_evidence["group_id"] == group_id_for(SITE_ID, GOAL)
    assert group_evidence["episode_ids"] == episode_ids

    # -- claim_persistence: stock genuinely decreasing 10 -> 6 -> 2 -------
    stock_entry = next(c for c in group_evidence["claim_persistence"] if c["claim_type"] == "stock_count")
    assert stock_entry["values"] == [10, 6, 2]
    assert stock_entry["unchanged_across_revisits"] is False
    assert stock_entry["verdict"] == "verified_true"
    assert stock_entry["plausible_change"] is True

    # -- viewer count frozen at 40 across 3 days: implausible, not "false" --
    viewer_entry = next(c for c in group_evidence["claim_persistence"] if c["claim_type"] == "viewer_count")
    assert viewer_entry["unchanged_across_revisits"] is True
    assert viewer_entry["verdict"] == "implausible"
    assert viewer_entry["plausible_change"] is False
    all_verdicts = {c["verdict"] for c in group_evidence["claim_persistence"]}
    assert "false" not in all_verdicts

    # -- timer_reset_detection: countdown shows the exact same 02:00:00 on
    # every revisit despite days passing -- must be flagged as a reset.
    assert len(group_evidence["timer_reset_detection"]) == 2  # revisit0->1, revisit1->2
    assert all(t["reset_detected"] for t in group_evidence["timer_reset_detection"])

    # -- each member episode now references the group evidence file -------
    for episode_id in episode_ids:
        episode_path = os.path.join(storage_dir, episode_id, "episode.json")
        with open(episode_path, "r", encoding="utf-8") as f:
            episode = json.load(f)
        assert validate_v2(episode) == []
        ref_path = episode["episode"]["group_evidence_path"]
        assert ref_path == os.path.join("groups", group_id_for(SITE_ID, GOAL), "group_evidence.json")
        assert os.path.isfile(os.path.join(storage_dir, ref_path))

    # -- idempotency: re-running produces the same result (modulo extracted_at) --
    group_evidence_again = extract_group_evidence(SITE_ID, GOAL, storage_dir, baselines_path=baselines_path)
    a = dict(group_evidence)
    b = dict(group_evidence_again)
    a.pop("extracted_at")
    b.pop("extracted_at")
    assert a == b
