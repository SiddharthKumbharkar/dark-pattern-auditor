"""Aggregates llm/api_client.py's per-call usage.json files (written by
every backend into payload/<episode_id>/<role>[/<attribute>]/usage.json)
into per-episode token/cost totals -- so a real auto-audit run's spend
can be compared directly against Sun et al. 2026's reported ~287k
tokens / $0.52 per site.

CLI: `python3 llm/cost_aggregate.py` (or `dpa.py cost-report`).
"""

import json
import os
from typing import Dict, List, Optional


def _iter_usage_files(payload_root: str):
    if not os.path.isdir(payload_root):
        return
    for episode_id in sorted(os.listdir(payload_root)):
        episode_dir = os.path.join(payload_root, episode_id)
        if not os.path.isdir(episode_dir):
            continue
        for dirpath, _dirnames, filenames in os.walk(episode_dir):
            if "usage.json" in filenames:
                yield episode_id, os.path.join(dirpath, "usage.json")


def aggregate_by_episode(payload_root: str) -> Dict[str, Dict]:
    totals: Dict[str, Dict] = {}
    for episode_id, usage_path in _iter_usage_files(payload_root):
        with open(usage_path, "r", encoding="utf-8") as f:
            usage = json.load(f)
        bucket = totals.setdefault(
            episode_id,
            {"calls": 0, "input_tokens": 0, "output_tokens": 0, "estimated_cost_usd": 0.0, "cost_known_for_every_call": True},
        )
        bucket["calls"] += 1
        bucket["input_tokens"] += usage.get("input_tokens") or 0
        bucket["output_tokens"] += usage.get("output_tokens") or 0
        cost = usage.get("estimated_cost_usd")
        if cost is None:
            bucket["cost_known_for_every_call"] = False
        else:
            bucket["estimated_cost_usd"] += cost
    for bucket in totals.values():
        bucket["estimated_cost_usd"] = round(bucket["estimated_cost_usd"], 6)
    return totals


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    from config.settings import load_config, resolve_path

    parser = argparse.ArgumentParser(
        description="Per-episode token/cost totals from payload.root's usage.json files."
    )
    parser.add_argument("--config", default=None, help="Path to config.yaml")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    payload_root = resolve_path(cfg.payload.root)
    totals = aggregate_by_episode(payload_root)
    if not totals:
        print(f"No usage.json files found under {payload_root}.")
        return 0

    grand_tokens = 0
    grand_cost = 0.0
    any_unknown = False
    for episode_id, bucket in totals.items():
        tokens = bucket["input_tokens"] + bucket["output_tokens"]
        grand_tokens += tokens
        grand_cost += bucket["estimated_cost_usd"]
        any_unknown = any_unknown or not bucket["cost_known_for_every_call"]
        note = f"~${bucket['estimated_cost_usd']:.4f}"
        if not bucket["cost_known_for_every_call"]:
            note += " (incomplete -- some calls had no known per-token price)"
        print(f"{episode_id}: {bucket['calls']} call(s), {tokens} tokens, {note}")

    print()
    total_note = f"TOTAL: {grand_tokens} tokens, ~${grand_cost:.4f}"
    if any_unknown:
        total_note += " (incomplete)"
    print(total_note)
    print("Sun et al. 2026 reported ~287k tokens / $0.52 per site, for comparison.")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
