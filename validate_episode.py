#!/usr/bin/env python3
"""CLI: validate an episode JSON file against the canonical schema.

Usage:
    python3 validate_episode.py <path>                     # validate as-is
    python3 validate_episode.py <path> --target-version 2   # migrate v1 -> v2 first, then validate

Exit code 0 on pass, 1 on fail (including unreadable/malformed input).
"""

import argparse
import json
import sys

from journey.schema_migration import SchemaValidationError, load_episode, validate_v1


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate an episode JSON file against the canonical schema."
    )
    parser.add_argument("path", help="Path to an episode JSON file")
    parser.add_argument(
        "--target-version",
        type=int,
        choices=(1, 2),
        default=None,
        help=(
            "Validate against this schema version. Default: whatever the file's own "
            "schema_version implies (missing or 1 -> v1, 2 -> v2). Passing 2 against a v1 "
            "file runs the migration shim first -- this is how a v1 episode is proven to "
            "load cleanly under the v2 loader."
        ),
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)

    try:
        with open(args.path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"FAIL {args.path}")
        print(f"  <root>: could not read/parse file: {exc}")
        return 1

    file_version = raw.get("schema_version", 1)
    target_version = args.target_version or file_version

    if target_version == 1:
        errors = validate_v1(raw)
    elif target_version == 2:
        try:
            load_episode(args.path)
            errors = []
        except SchemaValidationError as exc:
            errors = exc.errors
    else:
        print(f"FAIL {args.path}")
        print(f"  <root>: unsupported --target-version {target_version!r}")
        return 1

    if errors:
        print(f"FAIL {args.path} (schema v{target_version}, {len(errors)} error(s))")
        for error in errors:
            print(f"  - {error}")
        return 1

    print(f"PASS {args.path} (schema v{target_version})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
