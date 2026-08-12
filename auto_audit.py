#!/usr/bin/env python3
"""CLI: fully automated post-recording pipeline for one episode -- evidence
extraction, code-agent attributes, a real Stage-2 LLM pass for all 7
attributes plus the coordinator (calling the Anthropic API with your own
ANTHROPIC_API_KEY), the final {overall, regions, verdicts} document, and
the HTML report -- in one command.

Usage:
    python3 auto_audit.py <episode_id> [--model claude-sonnet-5] [--dry-run]

Requires ANTHROPIC_API_KEY in your environment or in a .env file at the
project root (python-dotenv loads it automatically -- see .env, already
gitignored). This is the ONLY command in this tool that spends money --
record/extract-evidence/run-attributes are free, local computation. Use
--dry-run to see exactly what would be sent (token/image counts per call)
without calling the API or spending anything.

Stage 2 is automatically skipped (evidence/attributes/output/report still
run, free) when the episode looks empty -- goal explicitly abandoned via
the overlay, or only a single step captured (e.g. a bot-walled landing
page and nothing else happened). See _looks_empty() / --force-stage2.

Each Stage-2 response is validated by journey/mechanism_verdict_ingest.py's
ingest_response() -- the EXACT same grounding/evidence-pointer/visual-claim
checks a human-pasted response.json goes through (see the manual workflow
this command replaces: build-payload -> hand to an LLM by hand -> paste
response.json -> ingest-response). LLM responses aren't deterministic, so a
rejected response (or a transient API error) is retried up to --max-attempts
times before being skipped (logged, never silently dropped) rather than
aborting the whole run -- the same way run-attributes continues past one
agent's not_assessable. A rejection that never clears grounding leaves that
attribute on the code agent's own verdict, same as if Stage-2 had never run.
"""

import argparse
import json
import os
import sys
from typing import Dict, Optional

from dotenv import load_dotenv

from attribute_agents.base import ATTRIBUTES
from config.settings import load_config, resolve_path
from journey.attribute_runner import run_attributes
from journey.episode_output_builder import build_episode_output
from journey.evidence_extractor import extract_evidence
from journey.mechanism_verdict_ingest import IngestError, ingest_response
from journey.schema_migration import load_episode, validate_computed_output, validate_mechanism_verdict, validate_v2
from llm.api_client import ApiCallError, BudgetExceededError, DEFAULT_MAX_LLM_CALLS_PER_EPISODE, DEFAULT_MODEL, call_for_judgement
from llm.payload_builder import PayloadBuildError, build_payload
from recorder.interactive_v2 import EPISODE_FILENAME
from report import build_episode_report

# Both re-exported from llm.api_client, not redefined here: the hard
# per-episode call budget is enforced INSIDE call_for_judgement() itself
# (the lowest level every path to the LLM passes through), not by an
# auto_audit.py-local counter -- see that module's docstring. A direct/
# manual call_for_judgement() call outside this orchestrator hits the exact
# same gate, which a counter living only here could never see.


def _looks_empty(episode: Dict) -> Optional[str]:
    """Returns a human-readable reason to skip the real Stage-2 spend, or
    None if the episode has enough in it to be worth judging. Deliberately
    narrow -- only the two unambiguous "nothing worth spending on" cases,
    not a step-count floor in general (a legitimately short flow, e.g. a
    2-step reject_cookies episode, is real evidence and must NOT be
    blocked here):
      - outcome.goal_achieved is False: the operator explicitly clicked
        the overlay's Abandon button -- a deliberate signal, not a guess,
        that this session didn't reach anything.
      - exactly one step: a lone navigate (e.g. the initial page load
        that hit a bot-check/access-denied wall and nothing else ever
        happened) can never contain a real finding regardless of outcome.
    See --force-stage2 to override."""
    steps = episode.get("steps") or []
    if len(steps) <= 1:
        return f"only {len(steps)} step(s) captured"
    if (episode.get("outcome") or {}).get("goal_achieved") is False:
        return "goal was explicitly marked abandoned"
    return None


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


def _run_stage2_call(
    target: str, role: str, attribute, model: str, operator: str,
    storage_dir: str, payload_root: str, dry_run: bool, max_attempts: int = 2,
    max_llm_calls: int = DEFAULT_MAX_LLM_CALLS_PER_EPISODE,
) -> bool:
    """Returns True on success (or a buildable dry-run), False if every
    attempt failed -- payload build, API call, or ingest rejection. Never
    raises for a per-call failure, so the caller can move on to the next
    attribute rather than losing the whole run over one bad response.
    BudgetExceededError (the per-episode call budget, enforced inside
    call_for_judgement() itself -- see llm/api_client.py) is the one
    exception that DOES propagate, deliberately not caught by the generic
    `except Exception` below -- see main().

    Retries up to `max_attempts` times on an API error or a grounding
    rejection: LLM responses aren't deterministic, and a rejection (e.g. an
    ungrounded visual claim) often succeeds on a fresh attempt -- verified
    manually twice against real sites (a rejected complexity response for
    bewakoof.com passed on retry with materially the same, correctly-
    grounded reasoning) before this retry was automated. Payload-build
    failures are NOT retried -- those are deterministic (a malformed
    episode, an unknown attribute), so retrying would just fail identically."""
    label = role + (f"/{attribute}" if attribute else "")
    try:
        manifest = build_payload(
            target, role=role, attribute=attribute, storage_dir=storage_dir, payload_root=payload_root
        )
    except PayloadBuildError as exc:
        print(f"  SKIP {label}: payload build failed -- {exc}")
        return False

    payload_dir = manifest["payload_dir"]
    if dry_run:
        est = manifest["token_estimate"]
        print(f"  DRY-RUN {label}: ~{est['estimated_tokens']} text tokens + {est['screenshot_count']} screenshot(s) -> {model}")
        return True

    response_path = os.path.join(payload_dir, "response.json")
    for attempt in range(1, max_attempts + 1):
        suffix = f" (attempt {attempt}/{max_attempts})" if max_attempts > 1 else ""

        try:
            judgement = call_for_judgement(payload_dir, model=model, max_calls=max_llm_calls)
        except ApiCallError as exc:
            print(f"  FAIL {label}{suffix}: {exc}")
            continue
        except BudgetExceededError:
            raise  # hard stop -- propagate to main(), do not retry or continue to the next attribute
        except Exception as exc:  # anthropic SDK network/auth/rate-limit errors
            print(f"  FAIL {label}{suffix}: {type(exc).__name__}: {exc}")
            continue

        with open(response_path, "w", encoding="utf-8") as f:
            json.dump(judgement, f, indent=2)

        try:
            ingest_response(
                target, role=role, response_file=response_path, model_name=model, operator=operator,
                attribute=attribute, storage_dir=storage_dir, payload_root=payload_root,
            )
        except IngestError as exc:
            print(f"  REJECTED {label}{suffix}: response failed grounding validation ({len(exc.errors)} error(s)):")
            for error in exc.errors:
                print(f"    - {error}")
            continue

        print(f"  OK   {label}{suffix}")
        return True

    print(f"  GIVING UP on {label} after {max_attempts} attempt(s) -- staying on the code agent's own verdict, if any.")
    return False


def main(argv=None) -> int:
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Fully automated pipeline: evidence -> attributes -> Stage-2 LLM pass -> output -> report."
    )
    parser.add_argument("episode", help="episode_id, episode directory, or episode.json path")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Anthropic model id for the Stage-2 pass (default: {DEFAULT_MODEL})")
    parser.add_argument("--operator", default=None, help="Recorded as the ingest operator (default: $DARK_PATTERN_OPERATOR or OS username)")
    parser.add_argument("--dry-run", action="store_true", help="Build payloads and print what would be sent, without calling the API or spending anything")
    parser.add_argument(
        "--max-attempts", type=int, default=2,
        help="Attempts per attribute/coordinator call before giving up on an API error or grounding rejection (default: 2)",
    )
    parser.add_argument(
        "--max-llm-calls", type=int, default=DEFAULT_MAX_LLM_CALLS_PER_EPISODE,
        help=f"Hard cap on real API call attempts for this episode, across all attributes and the "
             f"coordinator combined -- stops the run rather than the call if exceeded (default: "
             f"{DEFAULT_MAX_LLM_CALLS_PER_EPISODE})",
    )
    parser.add_argument("--config", default=None, help="Path to config.yaml")
    parser.add_argument(
        "--force-stage2", action="store_true",
        help=(
            "Run the Stage-2 LLM pass even when the episode looks empty -- goal explicitly "
            "abandoned via the overlay, or only a single step captured (e.g. a bot-walled landing "
            "page and nothing else). Without this flag, that case is skipped automatically (see "
            "_looks_empty()) so a blocked/dead session doesn't spend money finding out it had "
            "nothing to judge; evidence/attributes/output/report still run either way, free."
        ),
    )
    args = parser.parse_args(argv)

    if not args.dry_run and not os.environ.get("ANTHROPIC_API_KEY"):
        print("FAIL: ANTHROPIC_API_KEY is not set. Add it to .env at the project root, or export it, then retry.")
        print("      (Use --dry-run to preview this run without an API key.)")
        return 1

    operator = args.operator or os.environ.get("DARK_PATTERN_OPERATOR") or os.environ.get("USER") or "auto_audit"

    cfg = load_config(args.config)
    storage_dir = resolve_path(cfg.output.root)
    payload_root = resolve_path(cfg.payload.root)
    target = _resolve_target(args.episode, storage_dir)
    episode_json_path = _resolve_episode_json_path(target)

    print(f"1/5  extract-evidence  {target}")
    try:
        extract_evidence(episode_json_path)
    except Exception as exc:
        print(f"FAIL: extract-evidence failed -- {exc}")
        return 1

    print(f"2/5  run-attributes    {target}")
    try:
        run_attributes(episode_json_path, storage_dir=storage_dir)
    except Exception as exc:
        print(f"FAIL: run-attributes failed -- {exc}")
        return 1

    empty_reason = None if (args.dry_run or args.force_stage2) else _looks_empty(load_episode(episode_json_path))
    ok_count = 0
    coordinator_ok = False
    if empty_reason:
        print(
            f"3/5  Stage-2 LLM pass -- SKIPPED: {empty_reason}, nothing worth spending on "
            f"(use --force-stage2 to run it anyway)"
        )
    else:
        print(f"3/5  Stage-2 LLM pass ({args.model}){' [dry run]' if args.dry_run else ''}")
        try:
            for attribute in ATTRIBUTES:
                if _run_stage2_call(
                    target, "attribute", attribute, args.model, operator, storage_dir, payload_root,
                    args.dry_run, args.max_attempts, args.max_llm_calls,
                ):
                    ok_count += 1
            coordinator_ok = _run_stage2_call(
                target, "coordinator", None, args.model, operator, storage_dir, payload_root,
                args.dry_run, args.max_attempts, args.max_llm_calls,
            )
        except BudgetExceededError as exc:
            print(f"FAIL: {exc}")
            return 1

    if args.dry_run:
        print(
            f"\nDry run complete -- {ok_count}/{len(ATTRIBUTES)} attribute payload(s) buildable, "
            f"coordinator {'buildable' if coordinator_ok else 'not buildable'}. "
            f"No API calls made, nothing spent."
        )
        return 0

    if not empty_reason:
        print(f"    {ok_count}/{len(ATTRIBUTES)} attribute(s) ingested, coordinator {'ingested' if coordinator_ok else 'skipped/rejected'}")

    print(f"4/5  build-output       {target}")
    episode = load_episode(episode_json_path)
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

    print(f"5/5  report             {target}")
    report_path = build_episode_report(target)

    overall = computed_output["overall"]
    print()
    print(f"DONE  {report_path}")
    print(f"  verdict:                   {overall['verdict']}")
    print(f"  coverage_limited:          {overall['coverage_limited']}")
    print(f"  human_review_recommended:  {overall['human_review_recommended']}")
    print(f"  summary: {overall['summary']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
