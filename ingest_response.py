#!/usr/bin/env python3
"""CLI: ingest a manually-pasted LLM response.json back into a stored
episode's episode.mechanism_verdict.

Usage:
    python3 ingest_response.py <episode_id> --role attribute --file response.json \\
        --model "claude-opus-4-8" --operator "sid"
    python3 ingest_response.py <episode_id> --role coordinator --file response.json \\
        --model "claude-opus-4-8" --operator "sid"

Validates response.json against the exact response_schema.json build-payload
wrote (read from payload/<episode_id>/<role>/[<attribute>/]), rejects any
evidence_pointer whose step_id doesn't exist in this episode, then writes
into episode.mechanism_verdict.entries. Re-ingesting the same (role,
attribute) replaces its prior entry rather than accumulating a duplicate.
"""

import argparse
import os
import sys

from config.settings import load_config, resolve_path
from journey.mechanism_verdict_ingest import IngestError, ingest_response
from llm.payload_builder import ROLES


def _resolve_target(raw: str, storage_dir: str) -> str:
    if os.path.exists(raw):
        return raw
    candidate = os.path.join(storage_dir, raw)
    if os.path.isdir(candidate):
        return candidate
    return raw


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Ingest a manually-pasted LLM response.json into episode.mechanism_verdict."
    )
    parser.add_argument("episode", help="episode_id, episode directory, or episode.json path")
    parser.add_argument("--role", choices=ROLES, required=True)
    parser.add_argument("--file", dest="response_file", required=True, help="Path to the pasted response.json")
    parser.add_argument("--model", dest="model_name", required=True, help="Which model produced this response")
    parser.add_argument("--operator", required=True, help="Who is ingesting this response")
    parser.add_argument(
        "--attribute", default=None,
        help="Optional cross-check against response.json's own \"attribute\" field; only valid with --role attribute",
    )
    parser.add_argument("--payload-dir", default=None, help="Override payload.root from config.yaml for this run")
    parser.add_argument("--config", default=None, help="Path to config.yaml")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    storage_dir = resolve_path(cfg.output.root)
    payload_root = args.payload_dir or resolve_path(cfg.payload.root)
    target = _resolve_target(args.episode, storage_dir)

    try:
        episode = ingest_response(
            target,
            role=args.role,
            response_file=args.response_file,
            model_name=args.model_name,
            operator=args.operator,
            attribute=args.attribute,
            storage_dir=storage_dir,
            payload_root=payload_root,
        )
    except IngestError as exc:
        print(f"FAIL: response.json rejected ({len(exc.errors)} error(s)):")
        for error in exc.errors:
            print(f"  - {error}")
        return 1
    except (ValueError, FileNotFoundError) as exc:
        print(f"FAIL: {exc}")
        return 1

    # ingest_response() filters out any prior entry for this (role,
    # attribute) and appends the new one last, so it's always the final
    # entry in the list -- no need to re-derive the resolved attribute here.
    this_entry = episode["mechanism_verdict"]["entries"][-1]
    print(f"OK   ingested role={args.role} attribute={this_entry['attribute']} into {target}")
    print(f"  model_name:     {this_entry['model_name']}")
    print(f"  prompt_version: {this_entry['prompt_version']}")
    print(f"  ingested_at:    {this_entry['ingested_at']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
