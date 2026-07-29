#!/usr/bin/env python3
"""CLI: build a single, self-contained HTML report for one episode --
screenshot filmstrip, evidence tables, and every attribute verdict's
evidence pointers as clickable links to the screenshot they reference,
with a bounding box drawn over the specific element.

Usage:
    python3 report.py <episode_id>
    python3 report.py <episode_id> --out /tmp/report.html
"""

import argparse
import os
import sys
from typing import Optional

from config.settings import load_config, resolve_path
from journey.report_builder import build_report_data
from journey.report_html import render_html
from journey.schema_migration import load_episode
from recorder.interactive_v2 import EPISODE_FILENAME


def _resolve_target(raw: str, storage_dir: str) -> str:
    if os.path.exists(raw):
        return raw
    candidate = os.path.join(storage_dir, raw)
    if os.path.isdir(candidate):
        return candidate
    return raw


def build_episode_report(episode_path: str, out_path: Optional[str] = None) -> str:
    episode_json_path = episode_path if os.path.isfile(episode_path) else os.path.join(episode_path, EPISODE_FILENAME)
    episode_dir = os.path.dirname(episode_json_path)

    episode = load_episode(episode_json_path)
    data = build_report_data(episode, episode_dir)
    html = render_html(data)

    resolved_out = out_path or os.path.join(episode_dir, "report.html")
    os.makedirs(os.path.dirname(resolved_out) or ".", exist_ok=True)
    with open(resolved_out, "w", encoding="utf-8") as f:
        f.write(html)
    return resolved_out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a self-contained HTML report for one episode."
    )
    parser.add_argument("episode", help="episode_id, episode directory, or episode.json path")
    parser.add_argument("--out", default=None, help="Output HTML path (default: <episode_dir>/report.html)")
    parser.add_argument("--config", default=None, help="Path to config.yaml")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    storage_dir = resolve_path(cfg.output.root)
    target = _resolve_target(args.episode, storage_dir)

    try:
        out_path = build_episode_report(target, args.out)
    except (OSError, ValueError) as exc:
        print(f"FAIL: {exc}")
        return 1

    print(f"OK   {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
