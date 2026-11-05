#!/usr/bin/env python3
"""CLI: recompute baselines.json from a labelled-clean episode set.

Usage:
    python3 update_baselines.py --labels <labels.json>

labels.json: {"clean_episode_ids": ["episode_abc", "episode_def", ...]}
-- episode_ids a human has labelled as coming from honest sites (no dark
patterns), used as the reference population for "what does normal look
like" that thresholds are calibrated against.

Two kinds of signal, two collection paths:
  - Cross-revisit signals (claim persistence, timer drift) need 2+
    episodes of the same (site_id, goal) to compare across -- a single
    visit can't show how a claim behaves over time, so episodes are
    grouped first and groups smaller than 2 are skipped.
  - Single-episode signals (complexity's option_count) don't need a
    group at all -- every labelled-clean episode contributes
    independently, see _collect_complexity_samples().
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from typing import Dict, List, Tuple

from config.settings import load_config, resolve_path
from journey.baselines import Baseline, BaselineStore
from journey.evidence_extractor import extract_evidence
from journey.schema_migration import load_episode
from recorder.interactive_v2 import EPISODE_FILENAME
from signals.claim_persistence import compute_claim_persistence, group_claims_by_identity
from signals.timer_reset import compute_timer_drifts

# Never trips any plausibility branch -- when computing baselines we only
# read compute_claim_persistence()'s raw measurement fields
# (unchanged_across_revisits, elapsed_hours), not its verdict, so an
# inert placeholder threshold is deliberately used here instead of
# whatever's currently in baselines.json (which is exactly what this
# script is trying to replace).
_INERT_THRESHOLD = Baseline(median=1e9, p25=1e9, p75=1e9, n=0)


def _load_labels(path: str) -> List[str]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    episode_ids = data.get("clean_episode_ids")
    if not episode_ids:
        raise ValueError(f"{path} must contain a non-empty 'clean_episode_ids' list")
    return episode_ids


def _load_clean_episodes(storage_dir: str, episode_ids: List[str]) -> List[Dict]:
    episodes = []
    for episode_id in episode_ids:
        episode_dir = os.path.join(storage_dir, episode_id)
        episode_json_path = os.path.join(episode_dir, EPISODE_FILENAME)
        if not os.path.isfile(episode_json_path):
            print(f"  Warning: {episode_id!r} not found under {storage_dir}, skipping")
            continue
        episode = load_episode(episode_json_path)
        if not episode.get("evidence"):
            episode = extract_evidence(episode_dir)
        episodes.append({"episode_dir": episode_dir, "episode": episode})
    return episodes


def _group_by_site_and_goal(episodes: List[Dict]) -> Dict[Tuple[str, str], List[Dict]]:
    groups: Dict[Tuple[str, str], List[Dict]] = defaultdict(list)
    for entry in episodes:
        meta = entry["episode"]["episode"]
        groups[(meta["site_id"], meta["goal"])].append(entry)
    return {key: value for key, value in groups.items() if len(value) >= 2}


def _collect_complexity_samples(episodes: List[Dict]) -> Dict[str, List[float]]:
    """Unlike _collect_samples() below, these don't need a 2+ (site_id,
    goal) group -- option_count/reading_grade/total_actions are single-
    episode measurements, not cross-revisit comparisons, so every
    labelled-clean episode contributes independently.

    Per-episode MAX (not every step's own count) for option_count and
    reading_grade -- matching exactly what attribute_agents/complexity.py's
    _option_count_dimension/_reading_level_dimension actually threshold
    against (each takes the worst step in the episode), so the baseline is
    built from the same statistic it's compared to, not a different one.

    option_count is pooled GLOBALLY (not goal-scoped): real measured data
    across two different goals on this project's demo site showed the
    identical peak (14), confirming the dominant driver is constant,
    goal-independent page chrome (nav/cart/notification-prompt/a recorder
    testing overlay), not anything specific to the goal being pursued --
    unlike reading_grade, which genuinely does vary by goal (legal/
    cancellation copy reads denser than casual copy even on an honest
    site) and stays goal-scoped."""
    option_count_maxes: List[float] = []
    for entry in episodes:
        complexity_metrics = (entry["episode"].get("evidence") or {}).get("complexity_metrics") or {}
        option_counts = complexity_metrics.get("option_counts") or []
        if option_counts:
            option_count_maxes.append(max(o["option_count"] for o in option_counts))

    return {"complexity_option_count_threshold": option_count_maxes}


def _collect_samples(groups: Dict[Tuple[str, str], List[Dict]]) -> Dict[str, List[float]]:
    unchanged_hours: List[float] = []
    all_elapsed_hours: List[float] = []
    timer_drifts: List[float] = []

    for entries in groups.values():
        entries.sort(key=lambda e: e["episode"]["episode"]["revisit_index"])
        claims_by_revisit = [
            {
                "revisit_index": e["episode"]["episode"]["revisit_index"],
                "timestamp": (e["episode"].get("audit_metadata") or {}).get("audit_start_time") or "",
                "claims": (e["episode"].get("evidence") or {}).get("claim_extraction") or [],
            }
            for e in entries
        ]

        for result in compute_claim_persistence(claims_by_revisit, _INERT_THRESHOLD, _INERT_THRESHOLD):
            if result["elapsed_hours"] is None:
                continue
            all_elapsed_hours.append(result["elapsed_hours"])
            if result["unchanged_across_revisits"]:
                unchanged_hours.append(result["elapsed_hours"])

        for (claim_type, _selector), revisits in group_claims_by_identity(claims_by_revisit).items():
            if claim_type != "countdown_timer":
                continue
            timer_revisits = [
                {"revisit_index": r["revisit_index"], "timestamp": r["timestamp"], "remaining_seconds": r["normalized_value"]}
                for r in revisits
            ]
            timer_drifts.extend(compute_timer_drifts(timer_revisits))

    return {
        "claim_unchanged_hours_before_implausible": unchanged_hours,
        "timer_drift_tolerance_seconds": timer_drifts,
        "claim_min_elapsed_hours_for_verdict": all_elapsed_hours,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Recompute baselines.json from a labelled-clean episode set.")
    parser.add_argument("--labels", required=True, help='Path to a JSON file: {"clean_episode_ids": [...]}')
    parser.add_argument("--config", default=None, help="Path to config.yaml")
    parser.add_argument(
        "--baselines-path", default=None, help="Override baselines.json location (default: <project_root>/baselines.json)"
    )
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    storage_dir = resolve_path(cfg.output.root)

    try:
        episode_ids = _load_labels(args.labels)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAIL: {exc}")
        return 1

    episodes = _load_clean_episodes(storage_dir, episode_ids)
    groups = _group_by_site_and_goal(episodes)

    if not groups:
        print(
            "  Note: no (site_id, goal) group in the labelled-clean set has 2+ episodes -- "
            "cross-revisit signals (claim persistence, timer drift) can't be computed this run, "
            "but single-episode signals (complexity) don't need a group."
        )

    # Cross-revisit signals need 2+ episodes of the same (site_id, goal) to
    # compare across; single-episode signals (complexity) don't, so they're
    # collected from the full labelled-clean set regardless of grouping.
    samples: Dict[str, List[float]] = {}
    if groups:
        samples.update(_collect_samples(groups))
    samples.update(_collect_complexity_samples(episodes))

    store = BaselineStore(path=args.baselines_path)
    updated = []
    for key, values in samples.items():
        if not values:
            print(f"  Skipping {key!r}: no samples found in the labelled-clean set (left unchanged)")
            continue
        baseline = store.set_from_samples(key, values)
        updated.append(key)
        print(f"  {key}: median={baseline.median:.2f} p25={baseline.p25:.2f} p75={baseline.p75:.2f} n={baseline.n}")

    if not updated:
        print("FAIL: no baseline keys had any samples -- baselines.json left unchanged")
        return 1

    store.save()
    print(f"OK   {len(updated)} baseline(s) updated from {len(episodes)} labelled-clean episode(s) across {len(groups)} group(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
