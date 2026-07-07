#!/usr/bin/env python3
"""Auto-run the dark pattern auditing pipeline against demo-site/.

Starts the Next.js dev server (if one isn't already running on the target
port), waits for it to respond, drives a real click-through journey that
exercises all 8 demo-site dark patterns (Add to Cart, full checkout, free
trial signup, full cancellation flow), saves screenshots/DOM under
storage/ and the journey JSON to the project root, then shuts the dev
server back down (only if this script started it).

Usage:
    python3 scripts/audit_demo_site.py
    python3 scripts/audit_demo_site.py --audit-id my_run --port 3005
    python3 scripts/audit_demo_site.py --keep-server   # leave the dev server running afterward
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO_SITE_DIR = os.path.join(PROJECT_ROOT, "demo-site")
STORAGE_DIR = os.path.join(PROJECT_ROOT, "storage")

sys.path.insert(0, PROJECT_ROOT)

from config.exclusion_rules import load_exclusion_patterns  # noqa: E402
from journey.builder import JourneyBuilder  # noqa: E402
from recorder.browser import BrowserRecorder  # noqa: E402


def is_server_up(base_url: str) -> bool:
    try:
        urllib.request.urlopen(base_url, timeout=1.5)
        return True
    except Exception:
        return False


def wait_for_server(base_url: str, timeout_s: int = 30) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if is_server_up(base_url):
            return
        time.sleep(0.5)
    raise RuntimeError(f"Demo site did not respond at {base_url} within {timeout_s}s")


def run_audit(base_url: str, audit_id: str, output_path: str) -> None:
    recorder = BrowserRecorder(storage_dir=STORAGE_DIR, exclusion_patterns=load_exclusion_patterns())
    builder = JourneyBuilder(
        audit_id=audit_id,
        target_domain="auralis-demo.local",
        storage_dir=STORAGE_DIR,
        website_context={
            "domain": "auralis-demo.local",
            "industry": "ecommerce",
            "known_flow_types": [
                "product_browsing",
                "cart",
                "checkout",
                "subscription_trial",
                "subscription_cancellation",
            ],
        },
    )

    recorder.start()
    step_id = 0

    def capture(action_type="open_page", target_text=None):
        nonlocal step_id
        step_id += 1
        url = recorder.page.url
        step = recorder.capture_step(
            step_id=step_id, url=url, action_type=action_type, target_text=target_text
        )
        builder.add_step(step)
        print(f"  step {step_id:>2} ({action_type:<6}) excluded={step.get('capture_excluded')!s:<5} {url}")
        return step

    try:
        recorder.page.goto(f"{base_url}/")
        recorder.page.wait_for_timeout(1800)
        capture("open_page")

        recorder.page.click("text=No thanks, I don't like saving money")
        recorder.page.wait_for_timeout(300)

        recorder.page.goto(f"{base_url}/product/auralis-pro-x")
        recorder.page.wait_for_timeout(5600)  # let the nagging modal surface too
        capture("open_page")

        recorder.page.click("text=Add to cart")
        recorder.page.wait_for_timeout(400)

        recorder.page.goto(f"{base_url}/cart")
        recorder.page.wait_for_timeout(400)
        capture("click", "Add to cart")

        recorder.page.click("text=Proceed to checkout")
        recorder.page.wait_for_timeout(400)
        capture("click", "Proceed to checkout")

        recorder.page.click("text=Continue to payment")
        recorder.page.wait_for_timeout(400)
        capture("click", "Continue to payment")  # expected: excluded (payment URL pattern)

        recorder.page.click("text=Continue to review")
        recorder.page.wait_for_timeout(400)
        capture("click", "Continue to review")

        recorder.page.click("text=Place order")
        recorder.page.wait_for_timeout(400)
        capture("click", "Place order")

        recorder.page.goto(f"{base_url}/trial")
        recorder.page.wait_for_timeout(400)
        capture("open_page")

        recorder.page.click("text=Start My Free Trial")
        recorder.page.wait_for_timeout(400)
        capture("click", "Start My Free Trial")

        recorder.page.click("text=Manage membership")
        recorder.page.wait_for_timeout(400)
        capture("click", "Manage membership")

        recorder.page.click("text=Cancel membership")
        recorder.page.wait_for_timeout(400)
        capture("click", "Cancel membership")

        recorder.page.click("text=no thanks, cancel anyway")
        recorder.page.wait_for_timeout(400)
        capture("click", "no thanks, cancel anyway")

        recorder.page.click("text=yes, cancel my membership")
        recorder.page.wait_for_timeout(400)
        capture("click", "yes, cancel my membership")
    finally:
        recorder.stop()

    journey = builder.build()
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(journey, f, indent=2)

    print(f"\nTotal steps captured: {len(journey['journey_steps'])}")
    print(f"Journey saved to {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Auto-run the auditing pipeline against demo-site/")
    parser.add_argument("--audit-id", default="demo_site_full", help="Audit ID / output filename stem")
    parser.add_argument("--port", type=int, default=3000, help="Port the demo site should run on")
    parser.add_argument(
        "--keep-server", action="store_true", help="Leave the dev server running after the audit completes"
    )
    args = parser.parse_args()

    base_url = f"http://localhost:{args.port}"
    output_path = os.path.join(PROJECT_ROOT, f"output_{args.audit_id}.json")

    server_process = None

    try:
        if is_server_up(base_url):
            print(f"Demo site already running at {base_url}, using it as-is.")
        else:
            print(f"Starting demo site dev server on port {args.port}...")
            next_bin = os.path.join(DEMO_SITE_DIR, "node_modules", ".bin", "next")
            if not os.path.isfile(next_bin):
                raise SystemExit(
                    f"Could not find {next_bin} -- run `npm install` in demo-site/ first."
                )
            server_process = subprocess.Popen(
                [next_bin, "dev", "--port", str(args.port)],
                cwd=DEMO_SITE_DIR,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                wait_for_server(base_url)
            except RuntimeError:
                if server_process.poll() is not None:
                    raise SystemExit(
                        "next dev exited immediately -- most likely another dev server for "
                        "demo-site/ is already running on a different port (Next.js only allows "
                        "one `next dev` per project). Stop that one first, or omit --port to "
                        "reuse it automatically if it's on port 3000."
                    )
                raise
            print("Demo site is up.")

        run_audit(base_url, args.audit_id, output_path)
    finally:
        if server_process is not None and not args.keep_server:
            print("Stopping demo site dev server...")
            server_process.terminate()
            try:
                server_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server_process.kill()


if __name__ == "__main__":
    main()
