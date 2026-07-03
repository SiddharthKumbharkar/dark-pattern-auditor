"""Playwright session manager (Layer 1). Captures raw step state only —
classification and signal extraction happen in later layers."""

import json
import os
import time
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from playwright.sync_api import Browser, Page, Playwright, sync_playwright

from config.exclusion_rules import load_exclusion_patterns
from recorder.dom import extract_dom, extract_visible_text
from recorder.exclusion import is_excluded
from recorder.screenshot import capture_screenshot

VIEWPORT = {"width": 1440, "height": 900}

# Clicks are recorded into window.name (rather than an exposed Python
# function) because window.name is one of the few JS values that survives
# same-tab navigation — an expose_function() round-trip is async and can
# lose the race against the browser's own navigation on a real click.
_CLICK_LISTENER_JS = """
() => {
    if (window.__darkPatternClickListenerAttached__) {
        return;
    }
    window.__darkPatternClickListenerAttached__ = true;
    document.addEventListener('click', (event) => {
        const el = event.target;
        const text = ((el && (el.innerText || el.value)) || '').trim().slice(0, 100);
        const role = (el && (el.getAttribute('role') || el.tagName)) || '';
        window.name = JSON.stringify({text: text, role: role});
    }, true);
}
"""


class BrowserRecorder:
    def __init__(self, storage_dir: str, exclusion_patterns: Optional[List[str]] = None):
        self.storage_dir = storage_dir
        self.screenshots_dir = os.path.join(storage_dir, "screenshots")
        self.dom_dir = os.path.join(storage_dir, "dom")
        os.makedirs(self.screenshots_dir, exist_ok=True)
        os.makedirs(self.dom_dir, exist_ok=True)

        self.exclusion_patterns = (
            exclusion_patterns if exclusion_patterns is not None else load_exclusion_patterns()
        )

        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        self.navigation_log: List[str] = []
        self.console_errors: List[str] = []

        self.captured_steps: List[dict] = []
        self._interactive_step_counter = 0
        self._last_captured_url: Optional[str] = None

    def start(self) -> None:
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=False)
        self.page = self._browser.new_page(viewport=VIEWPORT)
        self.page.on("framenavigated", self._on_navigation)
        self.page.on("console", self._on_console)

    def start_interactive(self) -> List[dict]:
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=False)
        self.page = self._browser.new_page(viewport=VIEWPORT)

        self.captured_steps = []
        self._interactive_step_counter = 0
        self._last_captured_url = None
        self._inject_click_listener()

        print("Interactive recording started. Browse the site in the opened browser window.")
        print("Press Ctrl+C in this terminal to stop recording.")

        # No event listener here. Tested and confirmed: while the main thread
        # is idling in a pure time.sleep() loop with no other Playwright calls
        # in flight, neither a page.on("framenavigated", ...) handler nor a
        # self.page.url read reliably reflects navigations that happen from
        # real (non-Python-driven) browser activity — both silently miss
        # events. Only an actual round trip (evaluate()) forces the
        # connection to catch up, so that's what drives detection below.
        try:
            while True:
                self._poll_for_navigation()
                time.sleep(0.2)
        except KeyboardInterrupt:
            print("\nRecording stopped by user.")
        finally:
            self.stop()

        return self.captured_steps

    def _current_url(self) -> Optional[str]:
        try:
            return self.page.evaluate("window.location.href")
        except Exception:
            return None

    def _poll_for_navigation(self) -> None:
        url = self._current_url()
        if not url or url == "about:blank" or url == self._last_captured_url:
            return
        self._last_captured_url = url

        try:
            self.page.wait_for_timeout(1500)
        except Exception:
            pass

        # Re-check after settling in case of a client-side redirect chain
        # during the wait; capture the page it actually landed on.
        settled_url = self._current_url() or url
        self._last_captured_url = settled_url

        action_type, target_text, target_role = self._consume_pending_click()

        self._interactive_step_counter += 1
        step_id = self._interactive_step_counter

        try:
            step = self.capture_step(
                step_id=step_id,
                url=settled_url,
                action_type=action_type,
                target_text=target_text,
                target_role=target_role,
            )
        except Exception as exc:
            print(f"  Skipped step {step_id} (capture failed): {exc}")
            return

        self.captured_steps.append(step)
        print(f"Step {step_id} captured: {settled_url}")

        self._inject_click_listener()

    def _inject_click_listener(self) -> None:
        try:
            self.page.evaluate(_CLICK_LISTENER_JS)
        except Exception:
            pass

    def _consume_pending_click(self) -> Tuple[str, Optional[str], Optional[str]]:
        try:
            raw = self.page.evaluate("window.name")
        except Exception:
            return "open_page", None, None

        if not raw:
            return "open_page", None, None

        try:
            self.page.evaluate("window.name = ''")
        except Exception:
            pass

        try:
            info = json.loads(raw)
        except (TypeError, ValueError):
            return "open_page", None, None

        target_text = info.get("text") or None
        target_role = info.get("role") or None
        if not target_text and not target_role:
            return "open_page", None, None

        return "click", target_text, target_role

    def _on_navigation(self, frame) -> None:
        self.navigation_log.append(frame.url)

    def _on_console(self, message) -> None:
        if message.type == "error":
            self.console_errors.append(message.text)

    def capture_step(
        self,
        step_id: int,
        url: str,
        action_type: str,
        target_text: Optional[str] = None,
        target_role: Optional[str] = None,
    ) -> dict:
        timestamp = datetime.now(timezone.utc).isoformat()
        excluded, _matched_pattern = is_excluded(url, self.exclusion_patterns)

        user_action = {
            "action_type": action_type,
            "target_text": target_text,
            "target_role": target_role,
            "input_value_masked": None,
        }

        if excluded:
            return {
                "step_id": step_id,
                "timestamp": timestamp,
                "url": url,
                "user_action": user_action,
                "capture_excluded": True,
                "exclusion_reason": "url_pattern_match",
                "state_capture": None,
            }

        screenshot_filename = f"step_{step_id:03d}.png"
        dom_filename = f"step_{step_id:03d}.html"
        screenshot_path = os.path.join(self.screenshots_dir, screenshot_filename)
        dom_path = os.path.join(self.dom_dir, dom_filename)

        capture_screenshot(self.page, screenshot_path)

        dom_html = extract_dom(self.page)
        with open(dom_path, "w", encoding="utf-8") as f:
            f.write(dom_html)

        visible_text = extract_visible_text(self.page)

        return {
            "step_id": step_id,
            "timestamp": timestamp,
            "url": url,
            "page_title": self.page.title(),
            "page_type": None,  # classified by journey/ in a later layer
            "user_action": user_action,
            "capture_excluded": False,
            "exclusion_reason": None,
            "state_capture": {
                "screenshot_id": screenshot_filename,
                "dom_snapshot_id": dom_filename,
                "ocr_text_id": None,
                "accessibility_tree_id": None,
            },
            "visible_text_summary": visible_text,
            "extracted_signals": {
                "prices": [],
                "cart_items": [],
                "urgency_claims": [],
                "timers": [],
                "popups": [],
                "forms": [],
            },
            "extraction_confidence": {
                "ocr_used": False,
                "dom_extraction_complete": True,
                "low_confidence_fields": [],
            },
        }

    def stop(self) -> None:
        if self._browser is not None:
            try:
                self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                pass
            self._playwright = None
