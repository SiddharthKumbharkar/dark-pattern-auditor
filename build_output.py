#!/usr/bin/env python3
"""CLI: compute the unified audit output for a stored episode.

Usage:
    python3 build_output.py <episode_id | episode dir | episode.json path>

Writes episode.mechanism_verdict.computed_output (journey/episode_output_builder.py) --
the generated {overall, regions, verdicts} document, derived wholesale from
episode.attributes.results and any manually-ingested Stage-2 entries.
Idempotent: always fully replaces computed_output, so re-running after a
new run-attributes or ingest-response never leaves stale findings behind.
Safe to run before any coordinator response has been ingested -- regions
just won't have a likely_pattern until then.
"""

import argparse
import json
import os
import sys

from config.settings import load_config, resolve_path
from journey.episode_output_builder import build_episode_output
from journey.schema_migration import load_episode, validate_computed_output, validate_mechanism_verdict, validate_v2
from recorder.interactive_v2 import EPISODE_FILENAME


def _resolve_target(raw: str, storage_dir: str) -> str:
    if os.path.exists(raw):
        return raw
    candidate = os.path.join(storage_dir, raw)
    if os.path.isdir(candidate):
        return candidate
    return raw


def _resolve_episode_json_path(path: str) -> str:
    if os.path.isdir(path):
        return os.path.join(path, EPISODE_FILENAME)
    return path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Compute the unified audit output for a stored episode.")
    parser.add_argument("episode", help="episode_id, episode directory, or episode.json path")
    parser.add_argument("--config", default=None, help="Path to config.yaml")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    storage_dir = resolve_path(cfg.output.root)
    target = _resolve_target(args.episode, storage_dir)
    episode_json_path = _resolve_episode_json_path(target)

    try:
        episode = load_episode(episode_json_path)
    except (OSError, ValueError) as exc:
        print(f"FAIL: {exc}")
        return 1

    if not (episode.get("attributes") or {}).get("results"):
        print(f"FAIL: episode has no attribute results yet -- run run-attributes before build-output.")
        return 1

    computed_output = build_episode_output(episode)

    errors = validate_computed_output(computed_output)
    if errors:
        print(f"FAIL: computed output failed schema validation ({len(errors)} error(s)):")
        for error in errors:
            print(f"  - {error}")
        return 1

    mechanism_verdict = dict(episode.get("mechanism_verdict") or {})
    mechanism_verdict.setdefault("entries", [])
    mechanism_verdict["computed_output"] = computed_output

    mv_errors = validate_mechanism_verdict(mechanism_verdict)
    if mv_errors:
        print(f"FAIL: mechanism_verdict envelope failed schema validation ({len(mv_errors)} error(s)):")
        for error in mv_errors:
            print(f"  - {error}")
        return 1

    episode["mechanism_verdict"] = mechanism_verdict

    v2_errors = validate_v2(episode)
    if v2_errors:
        print(f"FAIL: episode failed v2 validation after build-output ({len(v2_errors)} error(s)):")
        for error in v2_errors:
            print(f"  - {error}")
        return 1

    with open(episode_json_path, "w", encoding="utf-8") as f:
        json.dump(episode, f, indent=2)

    overall = computed_output["overall"]
    regions = computed_output["regions"]

    print(f"OK   {target}")
    print(f"  verdict:                   {overall['verdict']}")
    print(f"  coverage_limited:          {overall['coverage_limited']}")
    print(f"  human_review_recommended:  {overall['human_review_recommended']}")
    rs = overall["regions_summary"]
    print(
        f"  regions_summary:           {rs['regions_with_findings']} with findings / "
        f"{rs['total_regions_examined']} examined ({rs['regions_clean']} clean)"
    )
    print(f"  summary: {overall['summary']}")
    print()
    if regions:
        print("  regions (strong first):")
        for region in regions:
            fired = ", ".join(a["attribute"] for a in region["attributes_fired"])
            pattern = region["likely_pattern"]["name"] if region["likely_pattern"] else "(none)"
            print(
                f"    [{region['finding_strength']:>8}] {region['ui_region']:<24} "
                f"fired: {fired or '(none)'}  likely_pattern: {pattern}"
            )
            for shared in region["shared_elements"]:
                where = f"{shared['selector']} (step {shared['step_id']})" if shared["step_id"] is not None else shared["selector"]
                print(f"               same element -- {', '.join(shared['attributes'])}: {where}")
    else:
        print("  regions: (none)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
