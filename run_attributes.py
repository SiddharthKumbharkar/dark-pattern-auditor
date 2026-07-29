#!/usr/bin/env python3
"""CLI: run the attribute agents against a stored episode.

Usage:
    python3 run_attributes.py <episode_id | episode dir | episode.json path>
    python3 run_attributes.py <episode> --agents asymmetry_code_v1,complexity_code_v1

Writes episode.attributes. Idempotent: always fully replaces it, so
re-running (e.g. after group evidence or baselines are updated) never
accumulates duplicate results -- no re-recording needed.
"""

import argparse
import sys

from config.settings import load_config, resolve_path
from journey.attribute_runner import run_attributes


def _resolve_target(raw: str, storage_dir: str) -> str:
    import os

    if os.path.exists(raw):
        return raw
    candidate = os.path.join(storage_dir, raw)
    if os.path.isdir(candidate):
        return candidate
    return raw


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the attribute agents against a stored episode.")
    parser.add_argument("episode", help="episode_id, episode directory, or episode.json path")
    parser.add_argument(
        "--agents",
        default=None,
        help="Comma-separated agent_ids to run instead of config.yaml's attributes.enabled_agents (default: all registered agents)",
    )
    parser.add_argument("--config", default=None, help="Path to config.yaml")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    storage_dir = resolve_path(cfg.output.root)
    target = _resolve_target(args.episode, storage_dir)

    enabled_agents = args.agents.split(",") if args.agents else cfg.attributes.enabled_agents

    try:
        episode = run_attributes(target, storage_dir=storage_dir, enabled_agents=enabled_agents)
    except (ValueError, FileNotFoundError) as exc:
        print(f"FAIL: {exc}")
        return 1

    results = episode["attributes"]["results"]
    by_verdict = {}
    for result in results:
        by_verdict.setdefault(result["verdict"], []).append(result["attribute"])

    print(f"OK   {target}  ({len(results)} agent(s) run)")
    for verdict in ("fires", "unsure", "no", "not_assessable"):
        if verdict in by_verdict:
            print(f"  {verdict}: {', '.join(sorted(by_verdict[verdict]))}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
