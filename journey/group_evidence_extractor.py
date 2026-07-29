"""Cross-episode ("group") evidence extraction (Layer 2): signals that
need more than one episode of the same (site_id, goal) -- claim
persistence across revisits, timer-reset detection, and paired-flow
(e.g. signup vs cancel) comparison. Builds on top of each member
episode's own single-episode evidence (journey/evidence_extractor.py),
computed on demand if missing.

Writes output.root/groups/<group_id>/group_evidence.json and patches
episode.group_evidence_path on every member episode to point at it.
"""

import json
import os
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional

from journey.baselines import BaselineStore
from journey.evidence_extractor import extract_evidence
from journey.schema_migration import load_episode, validate_group_evidence, validate_v2
from recorder.interactive_v2 import EPISODE_FILENAME
from signals.claim_persistence import compute_claim_persistence, group_claims_by_identity
from signals.paired_flow import compare_paired_flows
from signals.timer_reset import detect_timer_resets

EXTRACTOR_VERSION = "group_evidence_extractor/1.0.0"
GROUP_EVIDENCE_FILENAME = "group_evidence.json"


def group_id_for(site_id: str, goal: Optional[str]) -> str:
    raw = f"{site_id}__{goal or 'no_goal'}"
    return re.sub(r"[^A-Za-z0-9_-]+", "_", raw)


def _find_group_episodes(storage_dir: str, site_id: str, goal: Optional[str]) -> List[Dict]:
    """Returns [{"episode_dir": str, "episode": dict}], sorted by
    revisit_index, for every episode under storage_dir whose (site_id,
    goal) matches."""
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
        if meta.get("site_id") == site_id and meta.get("goal") == goal:
            matches.append({"episode_dir": episode_dir, "episode": episode})

    matches.sort(key=lambda m: m["episode"]["episode"].get("revisit_index", 0))
    return matches


def _ensure_evidence(episode_dir: str, episode: Dict) -> Dict:
    """Returns episode with evidence populated -- computing it via
    extract_evidence() if it's missing (empty {}), never re-running it if
    already present (idempotent extraction is extract_evidence()'s own
    job; this just guarantees SOMETHING is there to read)."""
    if episode.get("evidence"):
        return episode
    return extract_evidence(episode_dir)


def _revisit_timestamp(episode: Dict) -> Optional[str]:
    return (episode.get("audit_metadata") or {}).get("audit_start_time")


def _build_claims_by_revisit(episodes: List[Dict]) -> List[Dict]:
    """episodes: the [{"episode_dir", "episode"}] wrapper list this module
    uses throughout -- NOT a raw episode.json list."""
    entries = []
    for wrapper in episodes:
        full_episode = wrapper["episode"]
        meta = full_episode["episode"]
        entries.append(
            {
                "revisit_index": meta["revisit_index"],
                "timestamp": _revisit_timestamp(full_episode) or "",
                "claims": ((full_episode.get("evidence") or {}).get("claim_extraction")) or [],
            }
        )
    return entries


def _compute_timer_reset_entries(claims_by_revisit: List[Dict], tolerance) -> List[Dict]:
    grouped = group_claims_by_identity(claims_by_revisit)
    results = []
    for (claim_type, selector), revisits in grouped.items():
        if claim_type != "countdown_timer":
            continue
        timer_revisits = [
            {"revisit_index": r["revisit_index"], "timestamp": r["timestamp"], "remaining_seconds": r["normalized_value"]}
            for r in revisits
        ]
        for entry in detect_timer_resets(timer_revisits, tolerance):
            entry["selector"] = selector
            results.append(entry)
    return results


def _compute_paired_flow_entries(episodes: List[Dict], storage_dir: str) -> List[Dict]:
    results = []
    seen_pairs = set()
    episodes_by_id = {e["episode"]["episode"]["episode_id"]: e for e in episodes}

    for entry in episodes:
        episode = entry["episode"]
        meta = episode["episode"]
        episode_id = meta["episode_id"]
        paired_id = meta.get("paired_episode_id")
        if not paired_id:
            continue

        pair_key = tuple(sorted((episode_id, paired_id)))
        if pair_key in seen_pairs:
            continue
        seen_pairs.add(pair_key)

        paired_entry = episodes_by_id.get(paired_id)
        if paired_entry is None:
            paired_dir = os.path.join(storage_dir, paired_id)
            paired_json = os.path.join(paired_dir, EPISODE_FILENAME)
            if not os.path.isfile(paired_json):
                continue  # linked episode not found on disk -- skip, don't guess
            try:
                paired_episode = _ensure_evidence(paired_dir, load_episode(paired_json))
            except Exception:
                continue
        else:
            paired_episode = _ensure_evidence(paired_entry["episode_dir"], paired_entry["episode"])

        friction_a = (episode.get("evidence") or {}).get("friction_metrics")
        friction_b = (paired_episode.get("evidence") or {}).get("friction_metrics")
        if not friction_a or not friction_b:
            continue

        results.append(compare_paired_flows(episode_id, paired_id, friction_a, friction_b))

    return results


def extract_group_evidence(
    site_id: str, goal: Optional[str], storage_dir: str, baselines_path: Optional[str] = None
) -> Dict:
    """Idempotent: always fully rebuilds and overwrites group_evidence.json
    and every member episode's group_evidence_path from what's currently
    on disk -- safe to re-run any time, no re-recording needed."""
    matches = _find_group_episodes(storage_dir, site_id, goal)
    if not matches:
        raise ValueError(f"no episodes found for site_id={site_id!r} goal={goal!r} under {storage_dir}")

    episodes = [{"episode_dir": m["episode_dir"], "episode": _ensure_evidence(m["episode_dir"], m["episode"])} for m in matches]

    baselines = BaselineStore(path=baselines_path)
    unchanged_threshold = baselines.get("claim_unchanged_hours_before_implausible")
    min_elapsed_threshold = baselines.get("claim_min_elapsed_hours_for_verdict")
    timer_tolerance = baselines.get("timer_drift_tolerance_seconds")

    claims_by_revisit = _build_claims_by_revisit(episodes)
    claim_persistence = compute_claim_persistence(claims_by_revisit, unchanged_threshold, min_elapsed_threshold)
    timer_reset_detection = _compute_timer_reset_entries(claims_by_revisit, timer_tolerance)
    paired_flow_comparison = _compute_paired_flow_entries(episodes, storage_dir)

    group_id = group_id_for(site_id, goal)
    group_dir = os.path.join(storage_dir, "groups", group_id)
    os.makedirs(group_dir, exist_ok=True)
    group_evidence_json_path = os.path.join(group_dir, GROUP_EVIDENCE_FILENAME)
    group_evidence_relative_path = os.path.relpath(group_evidence_json_path, storage_dir)

    group_evidence = {
        "schema_version": 1,
        "group_id": group_id,
        "site_id": site_id,
        "goal": goal,
        "extractor_version": EXTRACTOR_VERSION,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "episode_ids": [e["episode"]["episode"]["episode_id"] for e in episodes],
        "claim_persistence": claim_persistence,
        "timer_reset_detection": timer_reset_detection,
        "paired_flow_comparison": paired_flow_comparison,
    }

    errors = validate_group_evidence(group_evidence)
    if errors:
        print(f"  Warning: group_evidence failed v1 validation ({len(errors)} error(s)):")
        for error in errors:
            print(f"    - {error}")

    with open(group_evidence_json_path, "w", encoding="utf-8") as f:
        json.dump(group_evidence, f, indent=2)

    for member in episodes:
        episode_json_path = os.path.join(member["episode_dir"], EPISODE_FILENAME)
        with open(episode_json_path, "r", encoding="utf-8") as f:
            episode_on_disk = json.load(f)
        episode_on_disk.setdefault("episode", {})["group_evidence_path"] = group_evidence_relative_path
        errors = validate_v2(episode_on_disk)
        if errors:
            print(f"  Warning: {episode_json_path} failed v2 validation after group linking ({len(errors)} error(s)):")
            for error in errors:
                print(f"    - {error}")
        with open(episode_json_path, "w", encoding="utf-8") as f:
            json.dump(episode_on_disk, f, indent=2)

    return group_evidence
