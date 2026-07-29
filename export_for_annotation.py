#!/usr/bin/env python3
"""CLI: flat, one-row-per-(episode, attribute) export for human
annotation -- CSV or JSON. See journey/annotation_export.py.

Usage:
    python3 export_for_annotation.py <episode_id> [<episode_id> ...]
    python3 export_for_annotation.py <episode_id> --format json --out /tmp/labels.json
"""

import argparse
import csv
import json
import os
import sys

from config.settings import load_config, resolve_path
from journey.annotation_export import ANNOTATION_ROW_FIELDS, export_for_annotation


def _resolve_target(raw: str, storage_dir: str) -> str:
    if os.path.exists(raw):
        return raw
    candidate = os.path.join(storage_dir, raw)
    if os.path.isdir(candidate):
        return candidate
    return raw


def _write_csv(rows, out_path: str) -> None:
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ANNOTATION_ROW_FIELDS)
        writer.writeheader()
        for row in rows:
            flat = dict(row)
            flat["evidence_summary"] = json.dumps(row["evidence_summary"])
            writer.writerow(flat)


def _write_json(rows, out_path: str) -> None:
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Flat, one-row-per-(episode, attribute) export for human annotation."
    )
    parser.add_argument("episodes", nargs="+", help="One or more episode_ids, directories, or episode.json paths")
    parser.add_argument("--format", choices=["csv", "json"], default="csv")
    parser.add_argument("--out", default=None, help="Output file path (default: annotation_export.<format> under project root)")
    parser.add_argument("--config", default=None, help="Path to config.yaml")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    storage_dir = resolve_path(cfg.output.root)
    targets = [_resolve_target(e, storage_dir) for e in args.episodes]
    out_path = args.out or resolve_path(f"annotation_export.{args.format}")

    try:
        rows = export_for_annotation(targets, storage_dir)
    except (ValueError, FileNotFoundError) as exc:
        print(f"FAIL: {exc}")
        return 1

    if args.format == "csv":
        _write_csv(rows, out_path)
    else:
        _write_json(rows, out_path)

    print(f"OK   wrote {len(rows)} row(s) from {len(targets)} episode(s) to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
