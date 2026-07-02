"""Playwright session manager (Layer 1). Captures raw step state only —
classification and signal extraction happen in later layers."""

import os
from datetime import datetime, timezone
from typing import List, Optional

from playwright.sync_api import Browser, Page, Playwright, sync_playwright

from config.exclusion_rules import load_exclusion_patterns
from recorder.dom import extract_dom, extract_visible_text
from recorder.exclusion import is_excluded
from recorder.screenshot import capture_screenshot

VIEWPORT = {"width": 1440, "height": 900}


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

    def start(self) -> None:
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=False)
        self.page = self._browser.new_page(viewport=VIEWPORT)
        self.page.on("framenavigated", self._on_navigation)
        self.page.on("console", self._on_console)

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
    ) -> dict:
        timestamp = datetime.now(timezone.utc).isoformat()
        excluded, _matched_pattern = is_excluded(url, self.exclusion_patterns)

        user_action = {
            "action_type": action_type,
            "target_text": target_text,
            "target_role": None,
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
            self._browser.close()
            self._browser = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None
