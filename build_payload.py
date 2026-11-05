#!/usr/bin/env python3
"""CLI: assemble exactly what an LLM would receive for one episode/role,
and write it to disk for MANUAL use. Never calls any API.

Usage:
    python3 build_payload.py <episode_id> --role triage
    python3 build_payload.py <episode_id> --role attribute --attribute asymmetry
    python3 build_payload.py <episode_id> --role coordinator
    python3 build_payload.py <episode_id> --role attribute --attribute complexity --out /tmp/payloads

Writes payload/<episode_id>/<role>/ (payload/<episode_id>/attribute/<attribute>/
for --role attribute): prompt.txt, evidence_summary.json, response_schema.json,
screenshots/, manifest.json, INSTRUCTIONS.txt. See llm/payload_builder.py.
"""

import argparse
import os
import sys

from config.settings import load_config, resolve_path
from llm.payload_builder import ROLES, build_payload


def _resolve_target(raw: str, storage_dir: str) -> str:
    if os.path.exists(raw):
        return raw
    candidate = os.path.join(storage_dir, raw)
    if os.path.isdir(candidate):
        return candidate
    return raw  # let build_payload() report a clear "not found" error


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Assemble an offline LLM payload for one episode/role. Never calls an API."
    )
    parser.add_argument("episode", help="episode_id, episode directory, or episode.json path")
    parser.add_argument("--role", choices=ROLES, default="triage")
    parser.add_argument(
        "--attribute", default=None, help="Required when --role attribute; one of the 7 attribute ids"
    )
    parser.add_argument("--out", default=None, help="Override payload.root from config.yaml for this run")
    parser.add_argument("--config", default=None, help="Path to config.yaml")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    storage_dir = resolve_path(cfg.output.root)
    payload_root = args.out or resolve_path(cfg.payload.root)
    target = _resolve_target(args.episode, storage_dir)

    try:
        manifest = build_payload(
            target, role=args.role, attribute=args.attribute, storage_dir=storage_dir, payload_root=payload_root
        )
    except (ValueError, FileNotFoundError, AssertionError) as exc:
        print(f"FAIL: {exc}")
        return 1

    te = manifest["token_estimate"]
    print(f"OK   {manifest['payload_dir']}")
    print(f"  prompt_version:  {manifest['prompt_version']}")
    print(f"  screenshots:     {len(manifest['screenshot_step_mapping'])}")
    print(f"  token_estimate:  ~{te['estimated_tokens']} tokens ({te['text_chars']} chars, text only)")
    print(f"  checksum:        sha256:{manifest['checksum']['combined'][:16]}...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
