#!/usr/bin/env python3
"""CLI: compute episode.evidence for a stored (masked) episode.

Usage:
    python3 extract_evidence.py <episode_id | episode dir | episode.json path>
    python3 extract_evidence.py --all   # re-extract for every complete episode under output.root

Idempotent: re-running against the same stored episode always fully
replaces episode.evidence, never merges/appends into whatever was there
before -- no re-recording needed, purely reads what's already on disk.
"""

import argparse
import os
import sys

from config.settings import load_config, resolve_path
from journey.evidence_extractor import extract_evidence
from recorder.interactive_v2 import EPISODE_FILENAME


def _episode_dirs(storage_dir: str):
    if not os.path.isdir(storage_dir):
        return []
    dirs = []
    for name in sorted(os.listdir(storage_dir)):
        episode_dir = os.path.join(storage_dir, name)
        if os.path.isdir(episode_dir) and os.path.isfile(os.path.join(episode_dir, EPISODE_FILENAME)):
            dirs.append(episode_dir)
    return dirs


def _resolve_target(raw: str, storage_dir: str) -> str:
    """Accepts a bare episode_id, a full path to an episode directory, or
    a direct path to an episode.json file."""
    if os.path.exists(raw):
        return raw
    candidate = os.path.join(storage_dir, raw)
    if os.path.isdir(candidate):
        return candidate
    return raw  # let extract_one() report a clear "not found" error


def _extract_one(episode_path: str) -> bool:
    try:
        episode = extract_evidence(episode_path)
    except Exception as exc:
        print(f"FAIL {episode_path}: {exc}")
        return False
    evidence = episode.get("evidence") or {}
    claims = len(evidence.get("claim_extraction") or [])
    pairs = len(evidence.get("visual_asymmetry") or [])
    increases = len((evidence.get("price_drift") or {}).get("increases") or [])
    print(f"OK   {episode_path}  (claims={claims} visual_pairs={pairs} price_increases={increases})")
    return True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Compute episode.evidence for a stored (masked) episode.")
    parser.add_argument(
        "episode", nargs="?", help="episode_id, episode directory, or episode.json path"
    )
    parser.add_argument("--all", action="store_true", help="Re-extract for every complete episode under output.root")
    parser.add_argument("--config", default=None, help="Path to config.yaml")
    args = parser.parse_args(argv)

    if not args.all and not args.episode:
        parser.error("either an episode argument or --all is required")

    cfg = load_config(args.config)
    storage_dir = resolve_path(cfg.output.root)

    if args.all:
        episode_dirs = _episode_dirs(storage_dir)
        if not episode_dirs:
            print("(no complete episodes found)")
            return 0
        results = [_extract_one(d) for d in episode_dirs]
        failures = results.count(False)
        print(f"\n{len(results) - failures}/{len(results)} succeeded")
        return 1 if failures else 0

    target = _resolve_target(args.episode, storage_dir)
    return 0 if _extract_one(target) else 1


if __name__ == "__main__":
    sys.exit(main())
