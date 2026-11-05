#!/usr/bin/env python3
"""dpa — the single entry point for every command in this tool
(Dark Pattern Auditor). Each subcommand below is a thin dispatch to the
existing, independently-runnable top-level script's own main(argv) --
this file duplicates no argument-parsing logic, so `dpa.py <command>
--help` prints EXACTLY what running that script directly would. Every
script remains directly runnable on its own (python3 record.py ...) for
backward compatibility; dpa.py is the recommended, unified way in.

Usage:
    python3 dpa.py --help                  # list every command
    python3 dpa.py <command> --help        # that command's own full help
    python3 dpa.py <command> [args...]

Global flags (must come BEFORE the command name):
    --log-file <path>   JSON Lines log destination (default: logs/dpa.jsonl
                         under output.root's project, see logging_setup.py)
    --log-level <level>  DEBUG|INFO|WARNING|ERROR (default: INFO)

Exit codes: whatever the delegated command's own main(argv) returns --
dpa.py itself never reinterprets them. Structured logging: every
invocation logs a "command started"/"command finished"/"command crashed"
lifecycle event (JSON to the log file, human-readable to stdout) around
the delegated command, in addition to that command's own stdout output.
"""

import importlib
import logging
import sys
import time
from typing import List, Optional, Tuple

from logging_setup import configure_logging, log_extra

# command name -> (module to import, argv to prepend before the user's
# own remaining args). record.py exposes 4 sub-subcommands of its own
# (record/list-goals/list-episodes/recover) via ITS OWN argparse
# subparsers -- each is flattened here into its own top-level dpa.py
# command, dispatched by prepending record.py's own subcommand name.
COMMAND_TABLE = {
    "record":                 ("record", ["record"], "Start a human-driven interactive recording session"),
    "list-goals":              ("record", ["list-goals"], "List the configured goal library"),
    "list-episodes":           ("record", ["list-episodes"], "List recorded episodes under output.root"),
    "recover":                 ("record", ["recover"], "Rebuild episode.json for a session that crashed before End Session"),
    "audit":                   ("audit", [], "Legacy v1 pipeline: URL-list or interactive journey recording"),
    "extract-evidence":        ("extract_evidence", [], "Compute episode.evidence for a stored (masked) episode"),
    "extract-group-evidence":  ("extract_group_evidence", [], "Compute cross-episode group evidence for a (site_id, goal)"),
    "run-attributes":          ("run_attributes", [], "Run the attribute agents against a stored episode"),
    "validate-episode":        ("validate_episode", [], "Validate an episode JSON file against the canonical schema"),
    "verify-masking":          ("verify_masking", [], "Re-scan a stored episode's artifacts for privacy leaks"),
    "update-baselines":        ("update_baselines", [], "Recompute baselines.json from labelled-clean episodes"),
    "build-payload":           ("build_payload", [], "Assemble an offline LLM payload for one episode/role"),
    "ingest-response":         ("ingest_response", [], "Ingest a manually-pasted LLM response.json"),
    "build-output":            ("build_output", [], "Compute the unified audit output (overall verdict + region-grouped findings)"),
    "auto-audit":              ("auto_audit", [], "Fully automated: evidence -> attributes -> real Stage-2 LLM pass (spends money) -> output -> report"),
    "cost-report":             ("llm.cost_aggregate", [], "Aggregate per-call token/cost usage.json files under payload.root, per episode"),
    "compare-verdicts":        ("compare_verdicts", [], "Reconcile code-agent vs manually-ingested LLM verdicts"),
    "export-for-annotation":   ("export_for_annotation", [], "Flat episode/attribute export for human annotation"),
    "validate-against-truth":  ("validate_against_truth", [], "Compare an episode against ground_truth.yaml"),
    "run-demo-suite":          ("run_demo_suite", [], "Guided known-answer test suite for the Auralis demo site"),
    "report":                  ("report", [], "Build a single-episode HTML report (--summary / --compare for presentation views)"),
    "report-site":             ("report_site", [], "Roll up every episode for one site_id into an HTML report"),
    "serve":                   ("serve", [], "Run the FastAPI dashboard backend (server.py) via uvicorn"),
}

_LOG_LEVELS = {"DEBUG": logging.DEBUG, "INFO": logging.INFO, "WARNING": logging.WARNING, "ERROR": logging.ERROR}


def _print_command_list() -> None:
    print(__doc__.strip())
    print("\nAvailable commands:\n")
    width = max(len(name) for name in COMMAND_TABLE)
    for name, (_module, _prefix, description) in COMMAND_TABLE.items():
        print(f"  {name.ljust(width)}  {description}")


def _split_global_flags(argv: List[str]) -> Tuple[Optional[str], str, List[str]]:
    """Global flags (--log-file, --log-level) must precede the command
    name -- everything from the command name onward is handed to that
    command's own parser untouched, so a command's OWN --log-file-shaped
    flag (if it ever had one) could never collide with dpa.py's."""
    log_file = None
    log_level = "INFO"
    i = 0
    while i < len(argv):
        if argv[i] == "--log-file" and i + 1 < len(argv):
            log_file = argv[i + 1]
            i += 2
        elif argv[i] == "--log-level" and i + 1 < len(argv):
            log_level = argv[i + 1]
            i += 2
        else:
            break
    return log_file, log_level, argv[i:]


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    log_file, log_level_name, rest = _split_global_flags(argv)

    if log_level_name.upper() not in _LOG_LEVELS:
        print(f"FAIL: --log-level must be one of {sorted(_LOG_LEVELS)}, got {log_level_name!r}")
        return 1
    logger = configure_logging(log_file=log_file, level=_LOG_LEVELS[log_level_name.upper()])

    if not rest or rest[0] in ("-h", "--help"):
        _print_command_list()
        return 0 if (rest and rest[0] in ("-h", "--help")) else 1

    command, command_args = rest[0], rest[1:]
    if command not in COMMAND_TABLE:
        print(f"FAIL: unknown command {command!r}\n")
        _print_command_list()
        logger.warning(f"unknown command: {command}", extra=log_extra(command=command))
        return 1

    module_name, prefix, _description = COMMAND_TABLE[command]

    logger.info(f"command started: {command}", extra=log_extra(command=command, args=command_args))
    start = time.time()
    # argparse's default `prog` is derived from sys.argv[0]'s basename --
    # swap it for the duration of the delegated call so a `--help`/error
    # usage line reads "usage: dpa.py <command> ..." (matching how it was
    # actually invoked) instead of the underlying script's own filename.
    original_argv0 = sys.argv[0]
    sys.argv[0] = f"dpa.py {command}"
    try:
        module = importlib.import_module(module_name)
        exit_code = module.main(prefix + command_args)
    except SystemExit:
        raise
    except Exception:
        logger.exception(f"command crashed: {command}", extra=log_extra(command=command))
        raise
    finally:
        sys.argv[0] = original_argv0
        duration = round(time.time() - start, 3)
        logger.info(f"command finished: {command}", extra=log_extra(command=command, duration_seconds=duration))

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
