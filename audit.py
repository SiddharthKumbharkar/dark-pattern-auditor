"""Main entry point: records a browsing journey and writes the journey JSON.

Phase 1 — open_page actions only, driven by a fixed list of URLs.
"""

import argparse
import json
from datetime import datetime, timezone

from config.exclusion_rules import load_exclusion_patterns
from journey.builder import JourneyBuilder
from recorder.browser import BrowserRecorder

STORAGE_DIR = "storage"


def parse_args() -> argparse.Namespace:
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
    parser.add_argument("--output", default=None, help="Path to write the final journey JSON")
    args = parser.parse_args()

    if not args.interactive and not args.urls:
        parser.error("--urls is required unless --interactive is set")

    return args


def main() -> None:
    args = parse_args()

    audit_id = args.audit_id or f"audit_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    output_path = args.output or f"output_{audit_id}.json"

    exclusion_patterns = load_exclusion_patterns()

    recorder = BrowserRecorder(storage_dir=STORAGE_DIR, exclusion_patterns=exclusion_patterns)
    builder = JourneyBuilder(
        audit_id=audit_id,
        target_domain=args.domain,
        storage_dir=STORAGE_DIR,
        website_context={"domain": args.domain, "industry": args.industry},
    )

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

    journey = builder.build()

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(journey, f, indent=2)

    if args.interactive:
        print(f"Recording stopped. Journey saved to {output_path}")
    else:
        print(f"Journey saved to {output_path}")


if __name__ == "__main__":
    main()
