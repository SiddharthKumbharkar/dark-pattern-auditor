"""Main entry point: records a browsing journey and writes the journey JSON.

Phase 1 — open_page actions only, driven by a fixed list of URLs.
"""

import argparse
import getpass
import json
import os
import sys
from datetime import datetime, timezone

from config.exclusion_rules import load_exclusion_patterns
from config.settings import load_config, resolve_path
from journey.builder import JourneyBuilder
from journey.manifest import write_run_manifest
from journey.privacy import PrivacyValidationError
from recorder.browser import BrowserRecorder


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dark pattern auditing journey recorder")
    parser.add_argument("--urls", default=None, help="Comma-separated list of URLs to visit in order (ignored with --interactive)")
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Launch a headed browser for manual human-driven recording instead of a fixed URL list",
    )
    parser.add_argument("--audit-id", default=None, help="Identifier for this audit (default: auto-generated timestamp)")
    parser.add_argument("--domain", required=True, help="Target domain name")
    parser.add_argument("--industry", required=True, help="Industry (ecommerce|saas|subscription_streaming|etc.)")
    parser.add_argument("--output", default=None, help="Path to write the final journey JSON (default: <output.root>/<audit_id>/journey.json)")
    parser.add_argument("--config", default=None, help="Path to config.yaml (default: $DARK_PATTERN_CONFIG or <project_root>/config.yaml)")
    parser.add_argument("--operator", default=None, help="Name/id of the human running this audit (default: $DARK_PATTERN_OPERATOR or OS username)")
    args = parser.parse_args(argv)

    if not args.interactive and not args.urls:
        parser.error("--urls is required unless --interactive is set")

    return args


def _default_operator() -> str:
    return os.environ.get("DARK_PATTERN_OPERATOR") or getpass.getuser()


def main(argv=None) -> int:
    args = parse_args(argv)
    cfg = load_config(args.config)

    audit_id = args.audit_id or f"audit_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    operator = args.operator or _default_operator()

    storage_dir = resolve_path(cfg.output.root)
    episode_dir = os.path.join(storage_dir, audit_id)
    output_path = args.output or os.path.join(episode_dir, "journey.json")

    exclusion_patterns = load_exclusion_patterns()

    recorder = BrowserRecorder(
        storage_dir=storage_dir,
        audit_id=audit_id,
        exclusion_patterns=exclusion_patterns,
        screenshot_full_page=cfg.capture.screenshot_full_page,
        privacy=cfg.privacy,
    )
    builder = JourneyBuilder(
        audit_id=audit_id,
        target_domain=args.domain,
        storage_dir=storage_dir,
        website_context={"domain": args.domain, "industry": args.industry},
        config=cfg,
    )

    try:
        if args.interactive:
            steps = recorder.start_interactive()
            for step in steps:
                builder.add_step(step)
        else:
            urls = [u.strip() for u in args.urls.split(",") if u.strip()]
            recorder.start()
            try:
                for step_id, url in enumerate(urls, start=1):
                    recorder.page.goto(url)
                    recorder.page.wait_for_timeout(2000)
                    step = recorder.capture_step(step_id=step_id, url=url, action_type="open_page")
                    builder.add_step(step)
                    print(f"Step {step_id} captured: {url}")
            finally:
                recorder.stop()
    except PrivacyValidationError as exc:
        print(f"Aborting run: privacy validation failed ({exc})", file=sys.stderr)
        return 1

    journey = builder.build()

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(journey, f, indent=2)

    write_run_manifest(episode_dir=episode_dir, audit_id=audit_id, config=cfg, operator=operator)

    if args.interactive:
        print(f"Recording stopped. Journey saved to {output_path}")
    else:
        print(f"Journey saved to {output_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
