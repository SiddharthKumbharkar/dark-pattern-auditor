#!/usr/bin/env python3
"""CLI: compare one episode's attribute verdicts against ground_truth.yaml
at the attribute level -- the known-answer test for the Auralis demo site.

Usage:
    python3 validate_against_truth.py <episode_id> --truth ground_truth.yaml
    python3 validate_against_truth.py <episode_id> --truth ground_truth.yaml --mode off

Mode (on/off) is auto-detected from the episode's site_domain
(localhost=on, 127.0.0.1=off -- see ground_truth.yaml's header comment)
unless --mode overrides it.
"""

import argparse
import os
import sys

from config.settings import load_config, resolve_path
from journey.ground_truth import GroundTruthError, load_ground_truth, validate_against_truth
from journey.schema_migration import load_episode
from recorder.interactive_v2 import EPISODE_FILENAME


def _resolve_target(raw: str, storage_dir: str) -> str:
    if os.path.exists(raw):
        return raw
    candidate = os.path.join(storage_dir, raw)
    if os.path.isdir(candidate):
        return candidate
    return raw


def _fmt(value) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


_COLUMNS = [
    ("attribute", lambda r: r["attribute"]),
    ("expected", lambda r: str(r["expected"])),
    ("code_verdict", lambda r: _fmt(r["code_verdict"])),
    ("detected?", lambda r: str(r["detected"])),
    ("class", lambda r: r["classification"]),
    ("notes", lambda r: r["notes"]),
]


def _format_table(rows) -> str:
    widths = [
        max(len(header), *(len(getter(r)) for r in rows)) if rows else len(header)
        for header, getter in _COLUMNS
    ]
    lines = ["  ".join(header.ljust(w) for (header, _), w in zip(_COLUMNS, widths))]
    lines.append("  ".join("-" * w for w in widths))
    for r in rows:
        lines.append("  ".join(getter(r).ljust(w) for (_, getter), w in zip(_COLUMNS, widths)))
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare one episode against ground_truth.yaml at the attribute level."
    )
    parser.add_argument("episode", help="episode_id, episode directory, or episode.json path")
    parser.add_argument("--truth", default=None, help="Path to ground_truth.yaml (default: project root)")
    parser.add_argument("--mode", choices=("on", "off"), default=None, help="Override auto-detected mode")
    parser.add_argument("--config", default=None, help="Path to config.yaml")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    storage_dir = resolve_path(cfg.output.root)
    truth_path = args.truth or resolve_path("ground_truth.yaml")
    target = _resolve_target(args.episode, storage_dir)
    episode_json_path = target if os.path.isfile(target) else os.path.join(target, EPISODE_FILENAME)

    try:
        ground_truth = load_ground_truth(truth_path)
        episode = load_episode(episode_json_path)
        result = validate_against_truth(episode, ground_truth, mode=args.mode)
    except (GroundTruthError, OSError, ValueError) as exc:
        print(f"FAIL: {exc}")
        return 1

    print(f"episode={result['episode_id']}  goal={result['goal']}  mode={result['mode']}")
    print()
    print(_format_table(result["rows"]))
    print()
    print(f"TP={result['tp']} FP={result['fp']} FN={result['fn']} TN={result['tn']}")
    print(f"precision={_fmt(result['precision'])} recall={_fmt(result['recall'])} f1={_fmt(result['f1'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
