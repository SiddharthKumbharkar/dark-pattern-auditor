#!/usr/bin/env python3
"""CLI: build a single, self-contained HTML report for one episode --
screenshot filmstrip, evidence tables, and every attribute verdict's
evidence pointers as clickable links to the screenshot they reference,
with a bounding box drawn over the specific element. This is the
TECHNICAL report -- unchanged by, and independent of, the summary views
below (see journey/report_summary_builder.py / report_summary_html.py):
same frozen episode data, read a second, presentation-only way. Neither
summary view touches this function or its output.

Usage:
    python3 report.py <episode_id>                          # report.html (technical, default)
    python3 report.py <episode_id> --out /tmp/report.html
    python3 report.py <episode_id> --summary                # + report_summary.html (plain-language)
    python3 report.py --compare <on_episode_id> <off_episode_id>   # report_compare.html (side by side)
"""

import argparse
import os
import sys
from typing import Optional

from config.settings import load_config, resolve_path
from journey.report_builder import build_report_data
from journey.report_html import render_html
from journey.report_summary_builder import build_summary_data, default_compare_label
from journey.report_summary_html import render_compare_html, render_summary_html
from journey.schema_migration import load_episode
from recorder.interactive_v2 import EPISODE_FILENAME


def _resolve_target(raw: str, storage_dir: str) -> str:
    if os.path.exists(raw):
        return raw
    candidate = os.path.join(storage_dir, raw)
    if os.path.isdir(candidate):
        return candidate
    return raw


def _episode_dir(episode_path: str) -> str:
    episode_json_path = episode_path if os.path.isfile(episode_path) else os.path.join(episode_path, EPISODE_FILENAME)
    return os.path.dirname(episode_json_path)


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


def build_episode_summary_report(episode_path: str, out_path: Optional[str] = None) -> str:
    """Presentation-only rendering mode of the SAME episode data
    build_episode_report() reads -- see journey/report_summary_builder.py's
    docstring. Writes report_summary.html alongside report.html by
    default; never writes to or reads report.html itself."""
    episode_dir = _episode_dir(episode_path)
    episode_json_path = episode_path if os.path.isfile(episode_path) else os.path.join(episode_path, EPISODE_FILENAME)
    episode = load_episode(episode_json_path)
    data = build_summary_data(episode, episode_dir)
    html = render_summary_html(data)

    resolved_out = out_path or os.path.join(episode_dir, "report_summary.html")
    os.makedirs(os.path.dirname(resolved_out) or ".", exist_ok=True)
    with open(resolved_out, "w", encoding="utf-8") as f:
        f.write(html)
    return resolved_out


def build_episode_compare_report(
    left_episode_path: str, right_episode_path: str, out_path: Optional[str] = None
) -> str:
    """Two independently-built summary datasets, rendered side by side --
    each column reads its own episode's own frozen data; nothing here
    compares or merges the two episodes' evidence, it only lays out two
    already-correct summaries next to each other.

    Column labels are ALWAYS derived from each episode's own data (see
    default_compare_label()) -- never the raw CLI argument or filesystem
    path the caller passed in. A full path is exactly the kind of
    internal detail this view exists to hide from a non-technical
    reader, and can be long enough to visually overflow a centered
    heading (found by literally screenshotting this view before
    shipping it)."""
    left_dir = _episode_dir(left_episode_path)
    left_json = left_episode_path if os.path.isfile(left_episode_path) else os.path.join(left_episode_path, EPISODE_FILENAME)
    right_json = right_episode_path if os.path.isfile(right_episode_path) else os.path.join(right_episode_path, EPISODE_FILENAME)

    left_data = build_summary_data(load_episode(left_json), left_dir)
    right_data = build_summary_data(load_episode(right_json), _episode_dir(right_episode_path))
    left_label = default_compare_label(left_data["meta"])
    right_label = default_compare_label(right_data["meta"])
    html = render_compare_html(left_data, right_data, left_label, right_label)

    resolved_out = out_path or os.path.join(left_dir, "report_compare.html")
    os.makedirs(os.path.dirname(resolved_out) or ".", exist_ok=True)
    with open(resolved_out, "w", encoding="utf-8") as f:
        f.write(html)
    return resolved_out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a self-contained HTML report for one episode."
    )
    parser.add_argument(
        "episode", nargs="?", default=None,
        help="episode_id, episode directory, or episode.json path (omit when using --compare)",
    )
    parser.add_argument("--out", default=None, help="Output HTML path")
    parser.add_argument(
        "--summary", action="store_true",
        help="Build the plain-language summary view (report_summary.html) instead of the technical "
             "report.html -- written alongside whatever report.html already exists for this episode "
             "(run `report <episode>` with no flags first/separately to build or refresh that). "
             "Never reads or rewrites report.html itself.",
    )
    parser.add_argument(
        "--compare", nargs=2, metavar=("ON_EPISODE", "OFF_EPISODE"), default=None,
        help="Build a side-by-side comparison view (report_compare.html) of two episodes instead of "
             "the single-episode report(s) above. Takes the place of the positional episode argument.",
    )
    parser.add_argument("--config", default=None, help="Path to config.yaml")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    storage_dir = resolve_path(cfg.output.root)

    if args.compare:
        left_raw, right_raw = args.compare
        left_target = _resolve_target(left_raw, storage_dir)
        right_target = _resolve_target(right_raw, storage_dir)
        try:
            out_path = build_episode_compare_report(left_target, right_target, out_path=args.out)
        except (OSError, ValueError) as exc:
            print(f"FAIL: {exc}")
            return 1
        print(f"OK   {out_path}")
        return 0

    if not args.episode:
        print("FAIL: episode is required unless --compare is given.")
        return 1

    target = _resolve_target(args.episode, storage_dir)

    if args.summary:
        # Deliberately does NOT also build/rewrite report.html -- the
        # technical report is untouched by this flag, see build_episode_summary_report()'s
        # docstring and this flag's own --help text.
        try:
            summary_out_path = build_episode_summary_report(target, args.out)
        except (OSError, ValueError) as exc:
            print(f"FAIL: {exc}")
            return 1
        print(f"OK   {summary_out_path}")
        return 0

    try:
        out_path = build_episode_report(target, args.out)
    except (OSError, ValueError) as exc:
        print(f"FAIL: {exc}")
        return 1
    print(f"OK   {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
