#!/usr/bin/env python3
"""CLI: roll up every recorded episode for one site_id -- across every
goal and revisit -- into a single overview HTML page, linking out to each
episode's own single-episode report (built alongside it if missing).

Usage:
    python3 report_site.py <site_id>
    python3 report_site.py <site_id> --out /tmp/site_report.html
"""

import argparse
import os
import sys
from typing import Dict

from config.settings import load_config, resolve_path
from journey.report_site_builder import build_site_report_data
from journey.report_html import render_site_html
from report import build_episode_report


def build_site_report(site_id: str, storage_dir: str, out_path: str, rebuild_episode_reports: bool = True) -> Dict:
    """Returns build_site_report_data()'s data dict (so callers -- the CLI
    -- can report episode/goal counts without recomputing it)."""
    data = build_site_report_data(site_id, storage_dir)

    report_links: Dict[str, str] = {}
    out_dir = os.path.dirname(out_path) or "."
    for episode in data["episodes"]:
        report_path = os.path.join(episode["episode_dir"], "report.html")
        if rebuild_episode_reports or not os.path.isfile(report_path):
            build_episode_report(episode["episode_dir"], out_path=report_path)
        report_links[episode["episode_id"]] = os.path.relpath(report_path, out_dir)

    html = render_site_html(data, report_links)
    os.makedirs(out_dir, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return data


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Roll up every recorded episode for one site_id into a single overview HTML page."
    )
    parser.add_argument("site_id", help="episode.episode.site_id to roll up (matches --site's host, e.g. localhost)")
    parser.add_argument("--out", default=None, help="Output HTML path (default: <output.root>/site_reports/<site_id>.html)")
    parser.add_argument(
        "--no-rebuild", action="store_true",
        help="Skip rebuilding per-episode reports that already exist (faster, may show stale data)",
    )
    parser.add_argument("--config", default=None, help="Path to config.yaml")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    storage_dir = resolve_path(cfg.output.root)
    out_path = args.out or os.path.join(storage_dir, "site_reports", f"{args.site_id}.html")

    try:
        data = build_site_report(args.site_id, storage_dir, out_path, rebuild_episode_reports=not args.no_rebuild)
    except (OSError, ValueError) as exc:
        print(f"FAIL: {exc}")
        return 1

    if not data["episodes"]:
        print(f"WARN: no episodes found for site_id={args.site_id!r} under {storage_dir}")

    print(f"OK   {out_path}  ({len(data['episodes'])} episode(s), {len(data['goals'])} goal(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
