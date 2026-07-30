"""Playwright session manager (Layer 1). Captures step state and masks it
BEFORE anything is written to storage_dir/<audit_id>/ -- CLAUDE.md's rule
("redaction happens BEFORE any data is written to storage") applies here
exactly as it does to recorder/interactive_v2.py's v2 pipeline; this
module used to write raw screenshots/DOM straight to disk with no masking
at all, which was a real gap (see recorder/masking/masker.py's
mask_dom_for_step/mask_screenshot_for_step, reused below)."""

import json
import os
import shutil
import tempfile
import time
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple

from playwright.sync_api import Browser, Page, Playwright, sync_playwright

from config.exclusion_rules import load_exclusion_patterns
from config.settings import PrivacyConfig
from journey.privacy import PrivacyValidationError
from recorder.dom import extract_dom, extract_visible_text
from recorder.exclusion import is_excluded
from recorder.masking.dom_masker import redact_text_span
from recorder.masking.masker import mask_dom_for_step, mask_screenshot_for_step, residual_pii_found
from recorder.masking.placeholders import tally_redactions
from recorder.redaction import redact_url
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
    def __init__(
        self,
        storage_dir: str,
        audit_id: str,
        exclusion_patterns: Optional[List[str]] = None,
        screenshot_full_page: bool = True,
        privacy: Optional[PrivacyConfig] = None,
    ):
        self.storage_dir = storage_dir
        self.audit_id = audit_id
        # Artifacts live under storage_dir/<audit_id>/ (the episode folder)
        # so concurrent/sequential audits never collide on step filenames.
        episode_dir = os.path.join(storage_dir, audit_id)
        self.screenshots_dir = os.path.join(episode_dir, "screenshots")
        self.dom_dir = os.path.join(episode_dir, "dom")
        os.makedirs(self.screenshots_dir, exist_ok=True)
        os.makedirs(self.dom_dir, exist_ok=True)

        self.screenshot_full_page = screenshot_full_page

        self.exclusion_patterns = (
            exclusion_patterns if exclusion_patterns is not None else load_exclusion_patterns()
        )

        # Masking is unconditional (not gated by privacy.enabled -- that
        # flag only controls journey/privacy.py's separate, narrower
        # user_action.input_value_masked check, matching
        # recorder/interactive_v2.py's v2 pipeline, which never checks
        # privacy.enabled around ITS masking calls either). strict and
        # keep_raw_artifacts are the only privacy settings this class reads.
        self.privacy = privacy or PrivacyConfig()
        # Raw screenshots are staged here (OUTSIDE the episode folder) and
        # never written into storage_dir/<audit_id>/ directly -- only the
        # masked copy is. Deleted at session end unless
        # privacy.keep_raw_artifacts (see cleanup_raw_artifacts/stop()).
        self._raw_tmp_dir = tempfile.mkdtemp(prefix=f"dpa_v1_raw_{audit_id}_")
        self.redactions_applied: List[Dict] = []
        self.masking_issue_found = False

        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        self.navigation_log: List[str] = []
        self.console_errors: List[str] = []

        self.captured_steps: List[dict] = []
        self._interactive_step_counter = 0
        self._last_captured_url: Optional[str] = None

        # Set to False (from any thread) to stop an in-progress
        # start_interactive() loop without a real KeyboardInterrupt.
        # Plain attribute assignment is atomic under the GIL, so no lock
        # is needed for this single boolean flag.
        self._running = False

    def cleanup_raw_artifacts(self) -> None:
        if self.privacy.keep_raw_artifacts:
            print(f"  privacy.keep_raw_artifacts is set -- raw screenshots kept at {self._raw_tmp_dir}")
            return
        shutil.rmtree(self._raw_tmp_dir, ignore_errors=True)

    def start(self) -> None:
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=False)
        self.page = self._browser.new_page(viewport=VIEWPORT)
        self.page.on("framenavigated", self._on_navigation)
        self.page.on("console", self._on_console)

    def start_interactive(
        self,
        start_url: Optional[str] = None,
        on_step: Optional[Callable[[dict], None]] = None,
        on_idle: Optional[Callable[[], None]] = None,
    ) -> List[dict]:
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=False)
        self.page = self._browser.new_page(viewport=VIEWPORT)

        self.captured_steps = []
        self._interactive_step_counter = 0
        self._last_captured_url = None
        self._inject_click_listener()

        if start_url:
            self.page.goto(start_url)

        print("Interactive recording started. Browse the site in the opened browser window.")
        print("Press Ctrl+C in this terminal to stop recording.")

        # No event listener here. Tested and confirmed: while the main thread
        # is idling in a pure time.sleep() loop with no other Playwright calls
        # in flight, neither a page.on("framenavigated", ...) handler nor a
        # self.page.url read reliably reflects navigations that happen from
        # real (non-Python-driven) browser activity — both silently miss
        # events. Only an actual round trip (evaluate()) forces the
        # connection to catch up, so that's what drives detection below.
        self._running = True
        try:
            while self._running:
                self._poll_for_navigation(on_step=on_step)
                if on_idle is not None:
                    try:
                        on_idle()
                    except Exception:
                        pass
                time.sleep(0.2)
        except KeyboardInterrupt:
            print("\nRecording stopped by user.")
        finally:
            self._running = False
            self.stop()

        return self.captured_steps

    def next_step_id(self) -> int:
        """Reserve the next sequential interactive step id.

        Exposed publicly so out-of-band captures (e.g. a manually
        triggered screenshot) can share the same counter as
        navigation-driven steps instead of colliding with it.
        """
        self._interactive_step_counter += 1
        return self._interactive_step_counter

    def _current_url(self) -> Optional[str]:
        try:
            return self.page.evaluate("window.location.href")
        except Exception:
            return None

    def _poll_for_navigation(self, on_step: Optional[Callable[[dict], None]] = None) -> None:
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

        step_id = self.next_step_id()

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

        if on_step is not None:
            try:
                on_step(step)
            except Exception:
                pass

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

        url_redacted = redact_url(url)
        base = {
            "step_id": step_id,
            "timestamp": timestamp,
            "url": url_redacted,
            "page_title": self.page.title(),
            "page_type": None,  # classified by journey/ in a later layer
            "user_action": user_action,
            "capture_excluded": False,
            "exclusion_reason": None,
        }

        # 1. Screenshot goes to a RAW TEMP path outside the episode folder
        # first -- only the masked copy (step 4 below) ever lands under
        # self.screenshots_dir.
        screenshot_filename = f"step_{step_id:03d}.png"
        raw_screenshot_path = os.path.join(self._raw_tmp_dir, f"step_{step_id:03d}_raw.png")
        capture_screenshot(self.page, raw_screenshot_path, full_page=self.screenshot_full_page)

        # 2. DOM: extract, then mask BEFORE anything touches disk.
        dom_html = extract_dom(self.page)
        mask_result = mask_dom_for_step(self.page, dom_html)
        if mask_result.error:
            raise RuntimeError(f"dom masking failed for step {step_id}: {mask_result.error}")

        # 3. visible_text_summary is a second, separate live-page read (its
        # visibility filtering depends on computed styles, so it can't be
        # derived from the already-masked HTML string) -- redact it
        # span-by-span with the same primitive dom_masker.py uses for text
        # nodes, then fold it into the same residual-PII self-check as the
        # DOM before either is trusted.
        raw_visible_text = extract_visible_text(self.page)
        redacted_visible_text: List[str] = []
        text_redaction_kinds: List[str] = []
        for line in raw_visible_text:
            redacted_line, kinds = redact_text_span(line)
            redacted_visible_text.append(redacted_line)
            text_redaction_kinds.extend(kinds)

        found_residual_pii = mask_result.residual_pii_found or residual_pii_found(
            "\n".join(redacted_visible_text)
        )
        if found_residual_pii:
            self.masking_issue_found = True
            if self.privacy.strict:
                raise PrivacyValidationError(
                    f"step {step_id}: masking self-check found residual PII and privacy.strict is true"
                )
            # Non-strict: withhold this step's DOM/screenshot/visible-text
            # artifacts entirely rather than write anything that still
            # looks like PII -- never a "redact harder and hope" fallback.
            print(f"  Warning: step {step_id} withheld -- residual PII found after masking")
            return {
                **base,
                "state_capture": {
                    "screenshot_id": "",
                    "dom_snapshot_id": "",
                    "ocr_text_id": None,
                    "accessibility_tree_id": None,
                },
                "visible_text_summary": [],
                "extracted_signals": {
                    "prices": [], "cart_items": [], "urgency_claims": [],
                    "timers": [], "popups": [], "forms": [],
                },
                "extraction_confidence": {
                    "ocr_used": False, "dom_extraction_complete": False, "low_confidence_fields": [],
                },
            }

        # 4. Clean: write the masked DOM and the masked screenshot -- the
        # raw screenshot never leaves self._raw_tmp_dir.
        dom_filename = f"step_{step_id:03d}.html"
        dom_path = os.path.join(self.dom_dir, dom_filename)
        with open(dom_path, "w", encoding="utf-8") as f:
            f.write(mask_result.masked_dom_html)

        screenshot_path = os.path.join(self.screenshots_dir, screenshot_filename)
        screenshot_error = mask_screenshot_for_step(raw_screenshot_path, screenshot_path, mask_result.boxes_to_black_out)
        if screenshot_error:
            raise RuntimeError(f"screenshot masking failed for step {step_id}: {screenshot_error}")

        redaction_kinds = mask_result.dom_redaction_kinds + text_redaction_kinds
        if redaction_kinds:
            self.redactions_applied.extend(tally_redactions(step_id, redaction_kinds))

        return {
            **base,
            "state_capture": {
                "screenshot_id": screenshot_filename,
                "dom_snapshot_id": dom_filename,
                "ocr_text_id": None,
                "accessibility_tree_id": None,
            },
            "visible_text_summary": redacted_visible_text,
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
        self.cleanup_raw_artifacts()
