#!/usr/bin/env python3
"""CLI: compute cross-episode group evidence for a (site_id, goal).

Usage:
    python3 extract_group_evidence.py <site_id> <goal>

Joins every stored episode matching (site_id, goal) -- typically
revisit_index 0/1/2 of the same target -- and computes claim_persistence,
timer_reset_detection, and paired_flow_comparison across them. Writes
output.root/groups/<group_id>/group_evidence.json and points every member
episode's episode.group_evidence_path at it.

Idempotent: safe to re-run any time (e.g. after recording a new revisit)
-- always rebuilds from what's currently on disk, no re-recording needed.
"""

import argparse
import sys

from config.settings import load_config, resolve_path
from journey.group_evidence_extractor import extract_group_evidence, group_id_for


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Compute cross-episode group evidence for a (site_id, goal).")
    parser.add_argument("site_id", help="episode.episode.site_id to join episodes on")
    parser.add_argument("goal", help="episode.episode.goal to join episodes on (goal id from the goal library)")
    parser.add_argument("--config", default=None, help="Path to config.yaml")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    storage_dir = resolve_path(cfg.output.root)

    try:
        group_evidence = extract_group_evidence(args.site_id, args.goal, storage_dir)
    except ValueError as exc:
        print(f"FAIL: {exc}")
        return 1

    group_id = group_id_for(args.site_id, args.goal)
    print(
        f"OK   group={group_id}  episodes={len(group_evidence['episode_ids'])}  "
        f"claims={len(group_evidence['claim_persistence'])}  "
        f"timer_resets={sum(1 for t in group_evidence['timer_reset_detection'] if t['reset_detected'])}"
        f"/{len(group_evidence['timer_reset_detection'])}  "
        f"paired_flows={len(group_evidence['paired_flow_comparison'])}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
