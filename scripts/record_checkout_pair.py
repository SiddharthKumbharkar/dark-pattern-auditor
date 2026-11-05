#!/usr/bin/env python3
"""Record a matched ON/OFF pair of the Auralis product-checkout journey
(homepage -> product -> add to cart -> checkout -> confirmation) using
recorder/interactive_v2.py, the same scripted-Playwright-stands-in-for-a-
human pattern scripts/audit_demo_site.py uses for the v1 recorder and
tests/test_interactive_v2_e2e.py uses for v2 (real browser, real clicks,
rec._poll_tick() called directly instead of the blocking human-driven
poll loop).

Produces two schema-v2 episodes under storage_auralis_real/, matching the
existing episode_auralis_cancel_on_v2 / episode_auralis_cancel_off_v2
pair already recorded there:
    episode_auralis_checkout_on
    episode_auralis_checkout_off

The OFF run flips demo-site's client-side dark-pattern toggle
(localStorage key "auralis-demo-dark-patterns-enabled") to "false" via
page.add_init_script() BEFORE the first real navigation is captured, so
step 1 already reflects OFF -- not a mid-journey toggle.

Usage:
    python3 scripts/record_checkout_pair.py
    python3 scripts/record_checkout_pair.py --port 3010
"""

import argparse
import os
import subprocess
import sys
import time
import urllib.request

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from config.settings import load_config  # noqa: E402
from recorder.interactive_v2 import InteractiveRecorderV2  # noqa: E402

STORAGE_DIR = os.path.join(PROJECT_ROOT, "storage_auralis_real")
TOGGLE_KEY = "auralis-demo-dark-patterns-enabled"

GOAL_DESCRIPTION = (
    "Find and complete purchase of the lowest-priced option that satisfies "
    "the target product/service."
)


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


def record_one(base_url: str, mode: str, operator: str, config) -> str:
    episode_id = f"episode_auralis_checkout_{mode}"
    site_domain = f"auralis-{mode}.local"

    rec = InteractiveRecorderV2(
        storage_dir=STORAGE_DIR,
        episode_id=episode_id,
        site_url=f"{base_url}/",
        site_domain=site_domain,
        sector="ecommerce",
        goal_id="purchase_cheapest",
        goal_description=GOAL_DESCRIPTION,
        operator=operator,
        config=config,
        revisit_index=0,
        device="desktop",
    )
    page = rec.launch(headless=True)

    if mode == "off":
        # Flip the toggle for every future navigation in this session...
        page.add_init_script(
            f"window.localStorage.setItem('{TOGGLE_KEY}', 'false');"
        )
        # ...and for the one that already happened inside launch().
        page.evaluate(f"window.localStorage.setItem('{TOGGLE_KEY}', 'false')")
        page.reload()

    page.wait_for_timeout(600)
    rec._poll_tick()  # step 1: homepage

    # Confirm-shaming popup appears ~1.4s after load regardless of mode;
    # button text differs ("No thanks, I don't like saving money" vs
    # "No thanks") so match on the stable substring both share.
    page.wait_for_timeout(1200)
    try:
        page.click("button:has-text('No thanks')", timeout=3000)
        page.wait_for_timeout(300)
        rec._poll_tick()  # step 2: popup dismissed
    except Exception:
        pass  # popup didn't show (e.g. already dismissed) -- not fatal

    page.goto(f"{base_url}/product/auralis-pro-x")
    page.wait_for_timeout(600)
    rec._poll_tick()  # product page

    page.click("text=Add to cart")
    page.wait_for_timeout(400)
    rec._poll_tick()  # add to cart (basket-sneaking: protection plan only when ON)

    page.goto(f"{base_url}/cart")
    page.wait_for_timeout(400)
    rec._poll_tick()  # cart page

    page.click("text=Proceed to checkout")
    page.wait_for_timeout(400)
    rec._poll_tick()  # checkout/shipping

    page.click("text=Continue to payment")
    page.wait_for_timeout(400)
    rec._poll_tick()  # checkout/payment -- expected capture_excluded (payment URL pattern)

    page.click("text=Continue to review")
    page.wait_for_timeout(400)
    rec._poll_tick()  # checkout/review (drip-pricing fee revealed here when ON)

    page.click("text=Place order")
    page.wait_for_timeout(400)
    rec._poll_tick()  # checkout/confirmation

    rec._teardown_browser()
    rec._cleanup_raw_artifacts()
    episode = rec.finalize()

    print(f"  {episode_id}: {len(episode['steps'])} steps -> {rec.episode_dir}")
    return episode_id


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=3000)
    parser.add_argument("--site-dir", default="demo-site")
    parser.add_argument("--operator", default=os.environ.get("DARK_PATTERN_OPERATOR", "scripted"))
    parser.add_argument("--config", default=None)
    args = parser.parse_args()

    config = load_config(args.config)
    site_dir = os.path.join(PROJECT_ROOT, args.site_dir)
    base_url = f"http://localhost:{args.port}"

    server_process = None
    try:
        if is_server_up(base_url):
            print(f"Demo site already running at {base_url}, using it as-is.")
        else:
            next_bin = os.path.join(site_dir, "node_modules", ".bin", "next")
            print(f"Starting {args.site_dir} dev server on port {args.port}...")
            server_process = subprocess.Popen(
                [next_bin, "dev", "--port", str(args.port)],
                cwd=site_dir,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            wait_for_server(base_url)
            print(f"{args.site_dir} is up.")

        os.makedirs(STORAGE_DIR, exist_ok=True)
        episode_ids = []
        for mode in ("on", "off"):
            print(f"Recording {mode} ...")
            episode_ids.append(record_one(base_url, mode, args.operator, config))

        print("\nDone:")
        for eid in episode_ids:
            print(f"  {eid}")
    finally:
        if server_process is not None:
            print("Stopping demo site dev server...")
            server_process.terminate()
            try:
                server_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server_process.kill()


if __name__ == "__main__":
    main()
