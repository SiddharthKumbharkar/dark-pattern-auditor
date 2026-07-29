#!/usr/bin/env python3
"""CLI: guides the operator through recording every session the Auralis
known-answer test needs (patterns ON and OFF, each reachable goal, plus
the revisit runs for revisit-dependent patterns), then runs extraction,
attributes, and validation across all of them and produces one report.

Usage:
    python3 run_demo_suite.py

Resumable: progress is saved to storage/demo_suite_progress.json after
every confirmed session, so you can stop and re-run this command later --
already-confirmed sessions are skipped. Once every required session is
confirmed, the run automatically switches from the guided recording phase
to the processing phase and prints the consolidated report.

The interactive recorder (record.py) needs a real human driving a real
browser -- this script cannot and does not drive it for you. For each
pending session it prints the exact `record.py record` command to run in
another terminal, then waits for you to report back the resulting
episode_id (or type "auto" to let it find the most recently recorded
episode matching that session, or "skip" to leave it for later).

Exit code: 0 unless the OFF run produced a "fires" verdict on ANY
attribute (a hard failure -- false positives on a known-clean site are
never acceptable) or a genuine error occurred (bad ground truth, no
episodes found, etc). An incomplete run (sessions still pending) is NOT a
failure -- it exits 0 with a summary of what's left.
"""

import argparse
import os
import sys

from config.settings import load_config, resolve_path
from journey.demo_suite import (
    candidate_episodes,
    format_report,
    load_progress,
    process_confirmed_sessions,
    required_sessions,
    save_progress,
    suite_passed,
)
from journey.ground_truth import GroundTruthError, load_ground_truth
from journey.schema_migration import load_episode
from recorder.interactive_v2 import EPISODE_FILENAME

GOAL_WALKTHROUGH = {
    "purchase_cheapest": (
        "From the homepage, open a product, add it to cart, then complete checkout "
        "(shipping -> payment -> review -> place order)."
    ),
    "complete_signup": 'From the homepage, navigate to "Start a Free Trial" (/trial) and start the trial.',
    "cancel_subscription": (
        "You need an active trial/subscription first -- complete a complete_signup session before this one "
        'if you have not already. Then go to Account -> "Manage membership" -> Cancel, and walk the '
        "cancellation flow through to the end."
    ),
    "decline_addon": (
        "From the homepage, open a product and add it to cart. On /cart, UNCHECK the pre-added "
        '"Protection Plan" line item instead of completing checkout.'
    ),
}


def _instructions(session: dict, host: str, port: int, progress: dict) -> str:
    # The real connection URL is the SAME real host for every session
    # (ON and OFF alike) -- session["site_domain"] is a pure metadata
    # label (auralis-on.local/auralis-off.local), passed separately via
    # --site-domain, decoupled from what's actually connectable. Some dev
    # servers (Next.js's, notably) reject a request whose Host header
    # isn't the one they're configured for, so relying on the server
    # accepting an alternate real hostname (e.g. 127.0.0.1) is fragile --
    # this works against any dev server.
    url = f"http://{host}:{port}/"
    lines = [
        f"Session: goal={session['goal']}  mode={session['mode']}  revisit_index={session['revisit_index']}",
        f"  1. Open {url} in a fresh browser profile.",
    ]
    if session["mode"] == "off":
        lines.append('  2. Click the "Dark Patterns: ON" button in the header so it reads "Dark Patterns: OFF".')
        step = 3
    else:
        lines.append('  2. Confirm the header reads "Dark Patterns: ON" (it does by default in a fresh profile).')
        step = 3
    lines.append(f"  {step}. {GOAL_WALKTHROUGH[session['goal']]}")

    pair_flag = ""
    if session["pair_with"]:
        # required_sessions() always lists the OFF session before its
        # paired ON session specifically so this lookup succeeds -- ON is
        # the one that declares --pair-with, using OFF's by-then-known
        # episode_id (only one side needs to declare it; see
        # journey/demo_suite.py's required_sessions() docstring).
        paired_entry = progress.get(session["pair_with"])
        if paired_entry:
            pair_flag = f" --pair-with {paired_entry['episode_id']}"
        else:
            lines.append(
                f"  !! Record session {session['pair_with']!r} first -- this session needs its episode_id "
                f"for --pair-with."
            )
    lines.append(
        f"  {step + 1}. In another terminal, run:\n"
        f"       python3 record.py record --site {url} --site-domain {session['site_domain']} "
        f"--goal {session['goal']} --revisit-index {session['revisit_index']}{pair_flag}"
    )
    lines.append(f"  {step + 2}. Complete the flow, then press Ctrl+C (or use the overlay) to end the session.")
    return "\n".join(lines)


def _run_wizard(sessions, progress, storage_dir, host, port) -> None:
    for session in sessions:
        if session["session_key"] in progress:
            continue

        print()
        print(_instructions(session, host, port, progress))
        answer = input(
            "\nPaste the episode_id once recording is complete "
            "(or 'auto' to use the most recent matching recording, or 'skip'): "
        ).strip()

        if not answer or answer.lower() == "skip":
            print("  Skipped -- will ask again next run.")
            continue

        if answer.lower() == "auto":
            candidates = candidate_episodes(storage_dir, session["site_domain"], session["goal"], session["revisit_index"])
            if not candidates:
                print("  No matching recorded episode found -- skipping for now.")
                continue
            episode_id = candidates[0]["episode_id"]
            confirm = input(f"  Found {episode_id!r} -- use this? [Y/n]: ").strip().lower()
            if confirm not in ("", "y", "yes"):
                print("  Skipped -- will ask again next run.")
                continue
        else:
            episode_id = answer
            episode_dir = os.path.join(storage_dir, episode_id)
            episode_json_path = os.path.join(episode_dir, EPISODE_FILENAME)
            if not os.path.isfile(episode_json_path):
                print(f"  No complete episode found at {episode_dir} -- skipping for now.")
                continue
            episode = load_episode(episode_json_path)
            meta = episode.get("episode") or {}
            if (meta.get("site_domain"), meta.get("goal"), meta.get("revisit_index")) != (
                session["site_domain"], session["goal"], session["revisit_index"],
            ):
                print(
                    f"  Warning: {episode_id}'s (site_domain={meta.get('site_domain')}, goal={meta.get('goal')}, "
                    f"revisit_index={meta.get('revisit_index')}) doesn't match this session -- recording it anyway."
                )

        progress[session["session_key"]] = {
            "session_key": session["session_key"],
            "episode_id": episode_id,
            "goal": session["goal"],
            "mode": session["mode"],
            "revisit_index": session["revisit_index"],
            "site_domain": session["site_domain"],
        }
        save_progress(storage_dir, progress)
        print(f"  Confirmed: {session['session_key']} -> {episode_id}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Guided known-answer test suite for the Auralis demo site.")
    parser.add_argument("--truth", default=None, help="Path to ground_truth.yaml (default: project root)")
    parser.add_argument("--host", default="localhost", help="Host the Auralis dev server is reachable on (default: localhost)")
    parser.add_argument("--port", type=int, default=3000, help="Port the Auralis dev server is running on")
    parser.add_argument("--config", default=None, help="Path to config.yaml")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    storage_dir = resolve_path(cfg.output.root)
    truth_path = args.truth or resolve_path("ground_truth.yaml")

    try:
        ground_truth = load_ground_truth(truth_path)
    except GroundTruthError as exc:
        print(f"FAIL: {exc}")
        return 1

    sessions = required_sessions(ground_truth, cfg.revisit.offsets_hours)
    progress = load_progress(storage_dir)

    _run_wizard(sessions, progress, storage_dir, args.host, args.port)

    pending = [s for s in sessions if s["session_key"] not in progress]
    if pending:
        print(f"\n{len(sessions) - len(pending)}/{len(sessions)} sessions confirmed. Still pending:")
        for s in pending:
            print(f"  - {s['session_key']}")
        print("\nRun this command again once you've recorded the remaining sessions.")
        return 0

    print(f"\nAll {len(sessions)} sessions confirmed. Running extraction, attributes, and validation...\n")
    try:
        report = process_confirmed_sessions(progress, ground_truth, storage_dir)
    except (ValueError, FileNotFoundError) as exc:
        print(f"FAIL: {exc}")
        return 1

    print(format_report(report))
    return 0 if suite_passed(report) else 1


if __name__ == "__main__":
    sys.exit(main())
