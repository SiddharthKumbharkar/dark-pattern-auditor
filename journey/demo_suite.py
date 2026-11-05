"""Orchestration logic for run_demo_suite.py -- computing which recording
sessions the Auralis known-answer test needs, tracking which have been
confirmed by the operator (a resumable progress file, since each session
is a real human-driven recording that can take minutes and may span
multiple run_demo_suite.py invocations), and running the processing
pipeline (evidence -> group evidence -> attributes -> validate-against-
truth) once every required session is confirmed.

Layer 2: file I/O over already-recorded episodes, no browser, no LLM.
run_demo_suite.py owns the interactive wizard (prompting the operator);
everything here is a pure or file-I/O-only function so it can be tested
without driving a real terminal.
"""

import json
import os
from typing import Dict, List, Optional

from journey.attribute_runner import run_attributes
from journey.evidence_extractor import extract_evidence
from journey.ground_truth import validate_against_truth
from journey.group_evidence_extractor import GROUP_EVIDENCE_FILENAME, extract_group_evidence, group_id_for
from journey.schema_migration import load_episode
from recorder.interactive_v2 import EPISODE_FILENAME

# Which of config.yaml's 6 goals actually have a reachable flow on the
# Auralis demo site (verified against demo-site/src -- reject_cookies and
# unsubscribe_email have no corresponding page/flow anywhere in
# demo-site/ or demo-site-vite/). This is a fact about THIS demo site, not
# a generic config value, so it lives here rather than in config.yaml.
REACHABLE_GOALS = ["purchase_cheapest", "complete_signup", "cancel_subscription", "decline_addon"]

# This harness's on/off recording convention -- see ground_truth.yaml's
# header comment and journey/ground_truth.py's SITE_DOMAIN_TO_MODE. These
# are pure metadata labels (record.py's --site-domain flag), not real
# hostnames -- both modes connect to the same real dev server URL.
SITE_DOMAIN_BY_MODE = {"on": "auralis-on.local", "off": "auralis-off.local"}

PROGRESS_FILENAME = "demo_suite_progress.json"


def session_key(goal: str, mode: str, revisit_index: int) -> str:
    return f"{goal}__{mode}__r{revisit_index}"


def required_sessions(ground_truth: Dict, revisit_offsets_hours: List[int]) -> List[Dict]:
    """One (goal, off, r0) + (goal, on, r0) pair per reachable goal, paired
    with each other via paired_episode_id so restriction/disparate_treatment
    can compare them. Only ONE side needs to declare paired_episode_id for
    journey/group_evidence_extractor.py's paired-flow lookup to resolve it
    (it looks the other one up directly from storage_dir regardless of
    whether it reciprocally points back -- see _compute_paired_flow_entries)
    -- so OFF is listed (and must be recorded) FIRST, and only the ON
    session's pair_with is set, referencing OFF's by-then-known episode_id.
    Recording ON first would require --pair-with to reference an episode_id
    that doesn't exist yet, since record.py generates episode_ids itself.

    Goals referenced by a requires_revisit pattern get additional
    (goal, on, rN) sessions, one per configured revisit offset -- driven by
    ground_truth.yaml + config.yaml, not a hardcoded count."""
    revisit_goals = {p["goal"] for p in ground_truth["patterns"] if p.get("requires_revisit") and p["goal"]}

    sessions = []
    for goal in REACHABLE_GOALS:
        on_key = session_key(goal, "on", 0)
        off_key = session_key(goal, "off", 0)
        sessions.append({
            "session_key": off_key, "goal": goal, "mode": "off", "revisit_index": 0,
            "site_domain": SITE_DOMAIN_BY_MODE["off"], "pair_with": None,
        })
        sessions.append({
            "session_key": on_key, "goal": goal, "mode": "on", "revisit_index": 0,
            "site_domain": SITE_DOMAIN_BY_MODE["on"], "pair_with": off_key,
        })
        if goal in revisit_goals:
            for i, _hours in enumerate(revisit_offsets_hours, start=1):
                sessions.append({
                    "session_key": session_key(goal, "on", i), "goal": goal, "mode": "on", "revisit_index": i,
                    "site_domain": SITE_DOMAIN_BY_MODE["on"], "pair_with": None,
                })
    return sessions


def _progress_path(storage_dir: str) -> str:
    return os.path.join(storage_dir, PROGRESS_FILENAME)


def load_progress(storage_dir: str) -> Dict[str, Dict]:
    path = _progress_path(storage_dir)
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_progress(storage_dir: str, progress: Dict[str, Dict]) -> None:
    os.makedirs(storage_dir, exist_ok=True)
    with open(_progress_path(storage_dir), "w", encoding="utf-8") as f:
        json.dump(progress, f, indent=2)


def candidate_episodes(storage_dir: str, site_domain: str, goal: str, revisit_index: int) -> List[Dict]:
    """Every complete (has episode.json) episode under storage_dir whose
    site_domain/goal/revisit_index match, newest first -- used by the
    wizard's "auto-detect" path to suggest which just-recorded episode
    fills a given session slot."""
    if not os.path.isdir(storage_dir):
        return []
    matches = []
    for name in sorted(os.listdir(storage_dir)):
        episode_dir = os.path.join(storage_dir, name)
        episode_json_path = os.path.join(episode_dir, EPISODE_FILENAME)
        if not os.path.isfile(episode_json_path):
            continue
        try:
            episode = load_episode(episode_json_path)
        except Exception:
            continue
        meta = episode.get("episode") or {}
        if meta.get("site_domain") == site_domain and meta.get("goal") == goal and meta.get("revisit_index") == revisit_index:
            matches.append({"episode_id": meta["episode_id"], "mtime": os.path.getmtime(episode_json_path)})
    matches.sort(key=lambda m: m["mtime"], reverse=True)
    return matches


def process_confirmed_sessions(
    progress: Dict[str, Dict], ground_truth: Dict, storage_dir: str, baselines_path: Optional[str] = None
) -> Dict:
    """Runs extract_evidence -> extract_group_evidence (once per distinct
    (site_domain, goal) among confirmed sessions) -> run_attributes ->
    validate_against_truth over every confirmed session, then builds the
    consolidated report. Idempotent: every step it calls already fully
    replaces its own output, so re-running after re-recording one session
    is safe."""
    entries = list(progress.values())
    episode_dirs = {e["session_key"]: os.path.join(storage_dir, e["episode_id"]) for e in entries}

    for episode_dir in episode_dirs.values():
        extract_evidence(episode_dir)

    seen_groups = set()
    for e in entries:
        key = (e["site_domain"], e["goal"])
        if key in seen_groups:
            continue
        seen_groups.add(key)
        extract_group_evidence(e["site_domain"], e["goal"], storage_dir, baselines_path=baselines_path)

    for episode_dir in episode_dirs.values():
        run_attributes(episode_dir, storage_dir=storage_dir, baselines_path=baselines_path)

    results = []
    for e in entries:
        episode = load_episode(os.path.join(episode_dirs[e["session_key"]], EPISODE_FILENAME))
        results.append(validate_against_truth(episode, ground_truth, mode=e["mode"]))

    return _build_report(results, ground_truth, storage_dir)


def _build_report(results: List[Dict], ground_truth: Dict, storage_dir: str) -> Dict:
    on_results = [r for r in results if r["mode"] == "on"]
    off_results = [r for r in results if r["mode"] == "off"]

    false_positives = [
        {"episode_id": r["episode_id"], "goal": r["goal"], "attribute": row["attribute"]}
        for r in off_results for row in r["rows"] if row["detected"]
    ]

    tp = sum(r["tp"] for r in on_results)
    fp = sum(r["fp"] for r in on_results)
    fn = sum(r["fn"] for r in on_results)
    tn = sum(r["tn"] for r in on_results)
    precision = tp / (tp + fp) if (tp + fp) > 0 else None
    recall = tp / (tp + fn) if (tp + fn) > 0 else None
    if precision is not None and recall is not None and (precision + recall) > 0:
        f1 = 2 * precision * recall / (precision + recall)
    else:
        f1 = None

    revisit_goals = sorted({p["goal"] for p in ground_truth["patterns"] if p.get("requires_revisit") and p["goal"]})
    revisit_section = []
    for goal in revisit_goals:
        group_id = group_id_for(SITE_DOMAIN_BY_MODE["on"], goal)
        group_path = os.path.join(storage_dir, "groups", group_id, GROUP_EVIDENCE_FILENAME)
        if not os.path.isfile(group_path):
            continue
        with open(group_path, "r", encoding="utf-8") as f:
            group_evidence = json.load(f)
        revisit_section.append({
            "goal": goal,
            "claim_persistence": group_evidence["claim_persistence"],
            "timer_reset_detection": group_evidence["timer_reset_detection"],
        })

    return {
        "on_results": on_results,
        "off_results": off_results,
        "false_positives": false_positives,
        "aggregate": {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": precision, "recall": recall, "f1": f1},
        "revisit_section": revisit_section,
    }


def suite_passed(report: Dict) -> bool:
    """The suite's ONE hard-failure condition: any attribute firing on an
    OFF-mode (known-clean) episode. Missed ON-mode detections lower
    recall but do not fail the suite -- they're exactly what this harness
    exists to surface, not something to hide behind a nonzero exit code."""
    return len(report["false_positives"]) == 0


def _fmt(value) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def format_report(report: Dict) -> str:
    lines = ["=" * 78, "AURALIS DEMO SUITE REPORT", "=" * 78]

    lines.append("\n-- ON run: planted patterns detected vs missed --\n")
    for r in report["on_results"]:
        lines.append(f"[{r['goal']}] episode={r['episode_id']}")
        expected_rows = [row for row in r["rows"] if row["expected"]]
        if not expected_rows:
            lines.append("    (no expected attributes for this goal)")
        for row in expected_rows:
            tag = "DETECTED" if row["detected"] else "MISSED  "
            note = f"  ({row['notes']})" if row["notes"] else ""
            lines.append(f"    {tag}  {row['attribute']:<22}{note}")
        lines.append(f"    precision={_fmt(r['precision'])} recall={_fmt(r['recall'])} f1={_fmt(r['f1'])}")
        lines.append("")

    lines.append("-- OFF run: false positives --\n")
    if report["false_positives"]:
        for fp in report["false_positives"]:
            lines.append(
                f"  !!! FALSE POSITIVE !!!  goal={fp['goal']}  episode={fp['episode_id']}  "
                f"attribute={fp['attribute']}  fired with patterns OFF"
            )
    else:
        lines.append("  None -- no attribute fired on any OFF-mode episode.")

    lines.append("\n-- Revisit signals (claim_persistence / timer_reset_detection) --\n")
    if report["revisit_section"]:
        for section in report["revisit_section"]:
            lines.append(f"  goal={section['goal']}")
            if not section["claim_persistence"] and not section["timer_reset_detection"]:
                lines.append("    (no claim_persistence / timer_reset_detection entries)")
            for c in section["claim_persistence"]:
                lines.append(f"    claim_persistence: {c['claim_type']} {c['selector']} -> {c['verdict']}")
            for t in section["timer_reset_detection"]:
                lines.append(f"    timer_reset_detection: {t['selector']} reset_detected={t['reset_detected']}")
    else:
        lines.append("  (no revisit-dependent goals recorded)")

    agg = report["aggregate"]
    lines.append("\n-- Aggregate ON-run attribute-level metrics --\n")
    lines.append(f"  TP={agg['tp']} FP={agg['fp']} FN={agg['fn']} TN={agg['tn']}")
    lines.append(f"  precision={_fmt(agg['precision'])} recall={_fmt(agg['recall'])} f1={_fmt(agg['f1'])}")

    lines.append("\n" + "=" * 78)
    if report["false_positives"]:
        lines.append(f"SUITE FAILED: {len(report['false_positives'])} false positive(s) on the OFF run.")
    else:
        lines.append("SUITE PASSED: no false positives on the OFF run.")
    lines.append("=" * 78)
    return "\n".join(lines)
