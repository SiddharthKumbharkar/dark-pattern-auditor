#!/usr/bin/env python3
"""CLI: reconcile code-agent verdicts against manually-ingested LLM
verdicts for one episode. The disagreement set is the primary output --
see journey/verdict_reconciliation.py.

Usage:
    python3 compare_verdicts.py <episode_id>
"""

import argparse
import os
import sys

from config.settings import load_config, resolve_path
from journey.schema_migration import load_episode
from journey.verdict_reconciliation import compare_verdicts
from recorder.interactive_v2 import EPISODE_FILENAME


def _resolve_target(raw: str, storage_dir: str) -> str:
    if os.path.exists(raw):
        return raw
    candidate = os.path.join(storage_dir, raw)
    if os.path.isdir(candidate):
        return candidate
    return raw


def _fmt(value) -> str:
    return "—" if value is None else str(value)


def _agree_symbol(agree) -> str:
    if agree is None:
        return "?"
    return "yes" if agree else "NO"


_COLUMNS = [
    ("attribute", lambda r: r["attribute"]),
    ("code_verdict", lambda r: _fmt(r["code_verdict"])),
    ("llm_verdict", lambda r: _fmt(r["llm_verdict"])),
    ("agree?", lambda r: _agree_symbol(r["agree"])),
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


def _format_disagreements(rows) -> str:
    disagreements = [r for r in rows if r["agree"] is False]
    if not disagreements:
        return "No disagreements."
    lines = [f"Disagreements ({len(disagreements)}):"]
    for r in disagreements:
        lines.append(f"  {r['attribute']}:")
        lines.append(
            f"    code: {r['code_verdict']} (severity={r['code_severity']}, confidence={r['code_confidence']}) "
            f"-- {r['code_reasoning']}"
        )
        lines.append(
            f"    llm:  {r['llm_verdict']} (severity={r['llm_severity']}, confidence={r['llm_confidence']}) "
            f"-- {r['llm_reasoning']}"
        )
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Reconcile code-agent vs manually-ingested LLM verdicts for one episode."
    )
    parser.add_argument("episode", help="episode_id, episode directory, or episode.json path")
    parser.add_argument("--config", default=None, help="Path to config.yaml")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    storage_dir = resolve_path(cfg.output.root)
    target = _resolve_target(args.episode, storage_dir)
    episode_json_path = target if os.path.isfile(target) else os.path.join(target, EPISODE_FILENAME)

    try:
        episode = load_episode(episode_json_path)
    except (OSError, ValueError) as exc:
        print(f"FAIL: {exc}")
        return 1

    rows = compare_verdicts(episode)

    print(_format_table(rows))
    print()
    print(_format_disagreements(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
