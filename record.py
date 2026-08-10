#!/usr/bin/env python3
"""CLI for interactive (human-driven) recording sessions.

Usage:
    python3 record.py record --site <url> --goal <goal_id> [options]
    python3 record.py list-goals
    python3 record.py list-episodes
    python3 record.py recover <episode_id>   # rebuild episode.json for a session that crashed

--site/--goal/--revisit-index/--pair-with/--device are exactly the flags
specified for `record`. --sector/--locale/--operator/--config are optional
additions beyond that spec (schema v2's episode.sector/locale/operator need
a source, and every other entry point in this repo already takes
--operator/--config) -- all default sensibly if omitted.
"""

import argparse
import getpass
import json
import os
import sys
from datetime import datetime, timezone
from urllib.parse import urlsplit

from config.settings import load_config, resolve_path
from recorder.interactive_v2 import (
    EPISODE_FILENAME,
    EPISODE_META_FILENAME,
    InteractiveRecorderV2,
    recover_incomplete_episode,
)


def _default_operator() -> str:
    return os.environ.get("DARK_PATTERN_OPERATOR") or getpass.getuser()


def _new_episode_id() -> str:
    return f"episode_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')}Z"


def _site_domain(url: str) -> str:
    netloc = urlsplit(url).netloc or url
    return netloc.split("@")[-1].split(":")[0]


def cmd_list_goals(args, cfg) -> int:
    if not cfg.goals:
        print("(no goals configured)")
        return 0
    width = max(len(g.id) for g in cfg.goals)
    for goal in cfg.goals:
        print(f"{goal.id.ljust(width)}  {goal.description}")
    return 0


def _episode_rows(storage_dir: str):
    if not os.path.isdir(storage_dir):
        return []
    rows = []
    for name in sorted(os.listdir(storage_dir)):
        episode_dir = os.path.join(storage_dir, name)
        if not os.path.isdir(episode_dir):
            continue
        meta_path = os.path.join(episode_dir, EPISODE_META_FILENAME)
        episode_path = os.path.join(episode_dir, EPISODE_FILENAME)
        if not os.path.isfile(meta_path) and not os.path.isfile(episode_path):
            continue  # not a v2 episode directory (e.g. a v1 audit_* dir)

        status = "complete" if os.path.isfile(episode_path) else "incomplete (no episode.json)"
        goal_id, operator, step_count, site = "?", "?", "?", "?"
        if os.path.isfile(meta_path):
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            goal_id = meta.get("goal_id", "?")
            operator = meta.get("operator", "?")
            step_count = str(meta.get("step_count", "?"))
            site = meta.get("site_domain", "?")
        rows.append((name, status, site, goal_id, step_count, operator))
    return rows


def cmd_list_episodes(args, cfg) -> int:
    rows = _episode_rows(resolve_path(cfg.output.root))
    if not rows:
        print("(no episodes recorded yet)")
        return 0

    headers = ("episode_id", "status", "site", "goal", "steps", "operator")
    widths = [max(len(headers[i]), max(len(r[i]) for r in rows)) for i in range(len(headers))]
    print(" | ".join(h.ljust(w) for h, w in zip(headers, widths)))
    print("-+-".join("-" * w for w in widths))
    for row in rows:
        print(" | ".join(c.ljust(w) for c, w in zip(row, widths)))
    return 0


def cmd_record(args, cfg) -> int:
    goal = next((g for g in cfg.goals if g.id == args.goal), None)
    if goal is None:
        valid_ids = ", ".join(g.id for g in cfg.goals)
        print(f"Unknown --goal {args.goal!r}. Valid goal ids: {valid_ids}", file=sys.stderr)
        return 1

    if args.auto_audit:
        # Fail before launching the browser, not after a 10-minute session --
        # auto_audit.py checks this too, but only once the session is already over.
        from dotenv import load_dotenv
        load_dotenv()
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print(
                "FAIL: --auto-audit requires ANTHROPIC_API_KEY (set it in .env at the project "
                "root, or export it) -- checked now so a missing key doesn't cost you the session.",
                file=sys.stderr,
            )
            return 1

    storage_dir = resolve_path(cfg.output.root)

    if args.pair_with and not os.path.isdir(os.path.join(storage_dir, args.pair_with)):
        print(
            f"Warning: --pair-with {args.pair_with!r} does not match any existing episode "
            f"directory under {storage_dir} -- recording anyway.",
            file=sys.stderr,
        )

    episode_id = _new_episode_id()
    operator = args.operator or _default_operator()

    recorder = InteractiveRecorderV2(
        storage_dir=storage_dir,
        episode_id=episode_id,
        site_url=args.site,
        site_domain=args.site_domain or _site_domain(args.site),
        sector=args.sector or "unknown",
        goal_id=goal.id,
        goal_description=goal.description,
        operator=operator,
        config=cfg,
        revisit_index=args.revisit_index,
        device=args.device,
        locale=args.locale,
        paired_episode_id=args.pair_with,
    )
    recorder.start()

    if args.auto_audit:
        import auto_audit

        episode_dir = os.path.join(storage_dir, episode_id)
        print(f"\n--auto-audit: running the full pipeline for {episode_id} now...\n")
        audit_argv = [episode_dir]
        if args.model:
            audit_argv += ["--model", args.model]
        config_path = getattr(args, "config", None)
        if config_path:
            audit_argv += ["--config", config_path]
        return auto_audit.main(audit_argv)

    return 0


def cmd_recover(args, cfg) -> int:
    storage_dir = resolve_path(cfg.output.root)
    episode_dir = os.path.join(storage_dir, args.episode_id)
    if not os.path.isdir(episode_dir):
        print(f"No episode directory found at {episode_dir}", file=sys.stderr)
        return 1
    recover_incomplete_episode(episode_dir, cfg)
    return 0


def parse_args(argv=None):
    # --config is accepted BOTH before the subcommand (on the top-level
    # parser, the original convention here) AND after it (added to every
    # subparser below) -- every other script in this project takes
    # --config as a trailing flag, so accepting it there too keeps this
    # command consistent with the rest without breaking the original form.
    parser = argparse.ArgumentParser(description="Interactive (human-driven) episode recording")
    parser.add_argument("--config", default=None, help="Path to config.yaml")
    subparsers = parser.add_subparsers(dest="command", required=True)

    record_parser = subparsers.add_parser("record", help="Start a human-driven recording session")
    record_parser.add_argument("--site", required=True, help="URL to open at session start")
    record_parser.add_argument("--goal", required=True, help="Goal id from the goal library (see list-goals)")
    record_parser.add_argument("--revisit-index", type=int, default=0, help="0 = first visit")
    record_parser.add_argument(
        "--pair-with", default=None, help="episode_id this episode is paired with (e.g. cancel<->signup)"
    )
    record_parser.add_argument("--device", choices=("desktop", "mobile"), default="desktop")
    record_parser.add_argument("--sector", default=None, help="Industry/sector label (default: unknown)")
    record_parser.add_argument(
        "--site-domain", default=None,
        help=(
            "Override the recorded site_id/site_domain metadata independent of --site's actual "
            "connection host (default: derived from --site's own host:port). Useful for "
            "distinguishing two variants of the same reachable server -- e.g. patterns-on vs "
            "patterns-off recording sessions against the same dev server -- without relying on "
            "the server accepting an alternate Host header (some dev servers, e.g. Next.js, "
            "reject requests to 127.0.0.1 outright)."
        ),
    )
    record_parser.add_argument("--locale", default=None, help="Locale tag, e.g. en-IN (default: unset)")
    record_parser.add_argument(
        "--operator", default=None, help="Name/id of the human running this session (default: $DARK_PATTERN_OPERATOR or OS username)"
    )
    record_parser.add_argument(
        "--auto-audit", action="store_true",
        help=(
            "Once the session ends (Ctrl+C or the overlay's End session button), automatically "
            "run the full auto_audit.py pipeline (extract-evidence -> run-attributes -> a real "
            "Stage-2 LLM pass on all 7 attributes + coordinator -> build-output -> report). "
            "Spends money (calls a real LLM API with ANTHROPIC_API_KEY) -- checked up front, "
            "before the browser even launches, so a missing key fails fast rather than after "
            "you've spent the session traversing the site."
        ),
    )
    record_parser.add_argument(
        "--model", default=None,
        help="Anthropic model id for the auto-audit Stage-2 pass (only used with --auto-audit; default: llm.api_client.DEFAULT_MODEL)",
    )

    list_goals_parser = subparsers.add_parser("list-goals", help="List the configured goal library")
    list_episodes_parser = subparsers.add_parser("list-episodes", help="List recorded episodes under output.root")

    recover_parser = subparsers.add_parser(
        "recover", help="Rebuild episode.json for a session that crashed before End Session"
    )
    recover_parser.add_argument("episode_id")

    # default=argparse.SUPPRESS here (not None) is load-bearing: with a
    # shared namespace, a subparser argument that DOES have a default
    # unconditionally sets it into the namespace, clobbering whatever the
    # top-level --config already put there when the subparser's own
    # --config wasn't given. SUPPRESS means "only touch the namespace if
    # this flag was actually passed here" -- letting a top-level --config
    # survive, while a --config given after the subcommand still wins
    # (the more specific, later one), since it's a real, explicit value.
    for subparser in (record_parser, list_goals_parser, list_episodes_parser, recover_parser):
        subparser.add_argument("--config", default=argparse.SUPPRESS, help="Path to config.yaml")

    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    cfg = load_config(args.config)

    handlers = {
        "record": cmd_record,
        "list-goals": cmd_list_goals,
        "list-episodes": cmd_list_episodes,
        "recover": cmd_recover,
    }
    return handlers[args.command](args, cfg)


if __name__ == "__main__":
    sys.exit(main())
