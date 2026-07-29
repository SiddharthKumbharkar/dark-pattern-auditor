"""Interactive recording, Stage 1 (Layer 1): a human drives a headed
browser; this module only observes and persists what happens. No
autonomous agent, no LLM call anywhere in this file.

Architecture, in one paragraph: one Playwright BrowserContext is shared by
every tab. Each tracked Page gets the SAME init script (recorder/overlay.py)
re-injected automatically by Playwright on every document via
add_init_script -- that's what survives full navigations and SPA route
changes without any manual re-attachment. A single Python-side poll loop
(the same "evaluate() is the only reliable way to detect a real,
human-driven navigation" approach recorder/browser.py already uses and
documents) ticks over every tracked page: on a URL change it captures a
navigation-attached step; otherwise it drains that page's JS-side trigger
queue (one entry per click/input-commit/submit/significant-scroll) and
captures a standalone step for each. Network events are NOT polled -- CDP
Network-domain listeners (recorder/network_capture.py) push events
continuously in the background and are simply drained into whichever step
is being captured next.

Durability: every step is appended to steps.jsonl (flushed + fsynced)
the moment it's captured, and episode_meta.json (goal outcome, notes) is
rewritten on every state change -- so if the browser process dies with no
clean end_session, everything captured up to that point is already on
disk. finalize() (called from a normal end_session AND from the
KeyboardInterrupt/SIGTERM/crash paths) assembles those into a
schema-v2-valid episode.json.

Privacy: the raw screenshot for a step is written to a temp dir (deleted
at session end unless privacy.keep_raw_artifacts), never the episode
folder; the raw DOM never touches disk at all. recorder/masking/ runs on
both BETWEEN capture and persistence and produces the masked screenshot/
DOM that actually get written into screenshots/ and dom/. If a masking
self-check finds residual PII in what it just produced, that artifact is
withheld (capture_error records why) regardless of privacy.strict; strict
additionally stops the whole session (see _capture_step).
"""

import json
import os
import shutil
import signal
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from playwright.sync_api import BrowserContext, Page, sync_playwright

from config.settings import Config
from journey.manifest import write_run_manifest
from journey.privacy import PrivacyValidationError
from journey.schema_migration import validate_v2
from recorder.dom import extract_dom
from recorder.evidence_probe import capture_interactive_elements
from recorder.masking.masker import MASKER_VERSION, mask_dom_for_step, mask_screenshot_for_step
from recorder.masking.placeholders import tally_redactions
from recorder.network_capture import NetworkCapture
from recorder.overlay import build_injection_script
from recorder.redaction import redact_url
from recorder.screenshot import capture_screenshot

DESKTOP_VIEWPORT = {"width": 1440, "height": 900}
MOBILE_VIEWPORT = {"width": 390, "height": 844}

POLL_INTERVAL_SECONDS = 0.2
NAV_SETTLE_MS = 1200

STEPS_JSONL_FILENAME = "steps.jsonl"
EPISODE_META_FILENAME = "episode_meta.json"
EPISODE_FILENAME = "episode.json"

_FALLBACK_ACTION = {
    "type": "navigate",
    "selector": None,
    "boundingBox": None,
    "targetText": None,
    "targetRole": None,
    "inputRedacted": False,
}


@dataclass
class _TrackedPage:
    page: Page
    tab_id: str
    network: Optional[NetworkCapture]
    last_url: Optional[str] = None


@dataclass
class _EpisodeMeta:
    episode_id: str
    site_url: str
    site_domain: str
    sector: str
    goal_id: str
    goal_description: str
    revisit_index: int
    device_context: str
    locale: Optional[str]
    paired_episode_id: Optional[str]
    operator: str
    started_at: str
    ended_at: Optional[str] = None
    goal_achieved: Optional[bool] = None
    abandoned: bool = False
    notes: List[str] = field(default_factory=list)
    step_count: int = 0
    redactions_applied: List[Dict] = field(default_factory=list)  # {step_id, kind, count}
    # True if ANY step's masking self-check ever found residual PII in its
    # own output -- drives episode.privacy.validation_passed at finalize().
    masking_issue_found: bool = False

    def to_dict(self) -> Dict:
        return dict(self.__dict__)


class InteractiveRecorderV2:
    def __init__(
        self,
        storage_dir: str,
        episode_id: str,
        site_url: str,
        site_domain: str,
        sector: str,
        goal_id: str,
        goal_description: str,
        operator: str,
        config: Config,
        revisit_index: int = 0,
        device: str = "desktop",
        locale: Optional[str] = None,
        paired_episode_id: Optional[str] = None,
    ):
        self.config = config
        self.device = device
        self.episode_dir = os.path.join(storage_dir, episode_id)
        self.screenshots_dir = os.path.join(self.episode_dir, "screenshots")
        self.dom_dir = os.path.join(self.episode_dir, "dom")
        self.computed_styles_dir = os.path.join(self.episode_dir, "computed_styles")
        os.makedirs(self.screenshots_dir, exist_ok=True)
        os.makedirs(self.dom_dir, exist_ok=True)
        os.makedirs(self.computed_styles_dir, exist_ok=True)

        # Raw (unmasked) screenshots are written here, OUTSIDE the episode
        # folder, and never anywhere else -- deleted at session end unless
        # privacy.keep_raw_artifacts. The raw DOM never touches disk at
        # all (it only ever exists as an in-memory string, masked before
        # the first write). See _capture_step / _cleanup_raw_artifacts.
        self._raw_tmp_dir = tempfile.mkdtemp(prefix=f"dpa_raw_{episode_id}_")
        self._field_denylist = config.privacy.field_denylist
        self._query_param_denylist = config.privacy.query_param_denylist

        self._steps_jsonl_path = os.path.join(self.episode_dir, STEPS_JSONL_FILENAME)
        self._episode_meta_path = os.path.join(self.episode_dir, EPISODE_META_FILENAME)

        started_at = datetime.now(timezone.utc).isoformat()
        self._meta = _EpisodeMeta(
            episode_id=episode_id,
            site_url=site_url,
            site_domain=site_domain,
            sector=sector,
            goal_id=goal_id,
            goal_description=goal_description,
            revisit_index=revisit_index,
            device_context=device,
            locale=locale,
            paired_episode_id=paired_episode_id,
            operator=operator,
            started_at=started_at,
        )
        self._write_episode_meta()

        self._playwright = None
        self._browser = None
        self._context: Optional[BrowserContext] = None

        self._tracked: List[_TrackedPage] = []
        self._lock = threading.Lock()
        self._next_tab_number = 2  # "main" is tab 1
        self._step_id = 0
        self._should_end = False
        self._injection_script = build_injection_script(goal_description)

    # -- lifecycle -----------------------------------------------------

    def launch(self, headless: bool = False) -> Page:
        """Launches the browser, attaches the main tab, and navigates it
        to site_url. Split out from start() so tests can drive the real
        Page object directly (real clicks/inputs/scrolls) instead of
        running the blocking poll loop -- headless defaults to False (a
        human must be able to see and control the browser in production;
        every real caller uses the default) and is only overridden by
        tests that don't need a visible window."""
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=headless)

        viewport = MOBILE_VIEWPORT if self.device == "mobile" else DESKTOP_VIEWPORT
        context_kwargs = {"viewport": viewport}
        if self.device == "mobile":
            context_kwargs["is_mobile"] = True
            context_kwargs["has_touch"] = True
        self._context = self._browser.new_context(**context_kwargs)

        main_page = self._context.new_page()
        self._attach_page(main_page, tab_id="main")
        # Registered only after the main page exists: BrowserContext's
        # "page" event fires for every page created in the context,
        # including this new_page() call itself -- listening earlier
        # would double-attach the main page as a phantom second tab.
        self._context.on("page", self._on_new_page)

        try:
            main_page.goto(self._meta.site_url)
        except Exception as exc:
            print(f"  Warning: initial navigation failed ({exc}); continuing to record from about:blank.")

        return main_page

    def run_loop(self) -> None:
        """The blocking poll loop. Runs until an end_session command,
        Ctrl+C, or SIGTERM."""
        previous_sigterm = signal.getsignal(signal.SIGTERM)
        signal.signal(signal.SIGTERM, self._handle_sigterm)
        try:
            while not self._should_end:
                self._poll_tick()
                time.sleep(POLL_INTERVAL_SECONDS)
        except KeyboardInterrupt:
            print("\nRecording stopped by user (Ctrl+C).")
        finally:
            signal.signal(signal.SIGTERM, previous_sigterm)

    def start(self) -> Dict:
        self.launch(headless=False)

        print(f"Interactive recording started. Goal: {self._meta.goal_description}")
        print(f"Episode: {self._meta.episode_id}  ->  {self.episode_dir}")
        print("Use the on-page overlay's [End session] button, or Ctrl+C here, to stop.")

        try:
            self.run_loop()
        except PrivacyValidationError as exc:
            # Everything captured up to (and NOT including) the offending
            # step is already safely on disk -- finalize() below still
            # runs and persists exactly that.
            print(f"\nSession aborted (privacy.strict): {exc}")
        finally:
            self._teardown_browser()
            self._cleanup_raw_artifacts()

        return self.finalize()

    def _handle_sigterm(self, signum, frame) -> None:
        self._should_end = True

    def _cleanup_raw_artifacts(self) -> None:
        if self.config.privacy.keep_raw_artifacts:
            print(f"  privacy.keep_raw_artifacts is set -- raw screenshots kept at {self._raw_tmp_dir}")
            return
        shutil.rmtree(self._raw_tmp_dir, ignore_errors=True)

    def _teardown_browser(self) -> None:
        try:
            if self._context is not None:
                self._context.close()
        except Exception:
            pass
        try:
            if self._browser is not None:
                self._browser.close()
        except Exception:
            pass
        try:
            if self._playwright is not None:
                self._playwright.stop()
        except Exception:
            pass

    # -- tab tracking ----------------------------------------------------

    def _on_new_page(self, page: Page) -> None:
        with self._lock:
            if any(tracked.page is page for tracked in self._tracked):
                return  # already attached (e.g. the main page's own creation)
            tab_id = f"tab-{self._next_tab_number}"
            self._next_tab_number += 1
        self._attach_page(page, tab_id=tab_id)
        print(f"  New tab/popup attached: {tab_id}")

    def _attach_page(self, page: Page, tab_id: str) -> None:
        page.add_init_script(script=self._injection_script)

        network = None
        if self.config.capture.capture_network:
            try:
                cdp = self._context.new_cdp_session(page)
                network = NetworkCapture(cdp)
            except Exception as exc:
                print(f"  Warning: could not attach CDP network capture to {tab_id}: {exc}")

        with self._lock:
            self._tracked.append(_TrackedPage(page=page, tab_id=tab_id, network=network))

    # -- main poll loop ----------------------------------------------------

    def _poll_tick(self) -> None:
        with self._lock:
            tracked_snapshot = list(self._tracked)

        for tracked in tracked_snapshot:
            if self._should_end:
                return
            try:
                if tracked.page.is_closed():
                    self._forget_page(tracked)
                    continue
            except Exception:
                self._forget_page(tracked)
                continue

            try:
                self._service_commands(tracked)
                if self._should_end:
                    return
                self._service_page(tracked)
            except PrivacyValidationError:
                # A masking self-check failure in strict mode -- must stop
                # the session, not be logged and shrugged off like an
                # ordinary poll error. Propagates up through run_loop().
                raise
            except Exception as exc:
                print(f"  Warning: poll error on {tracked.tab_id}: {exc}")

    def _forget_page(self, tracked: _TrackedPage) -> None:
        with self._lock:
            if tracked in self._tracked:
                self._tracked.remove(tracked)

    def _current_url(self, page: Page) -> Optional[str]:
        try:
            return page.evaluate("window.location.href")
        except Exception:
            return None

    def _service_page(self, tracked: _TrackedPage) -> None:
        url = self._current_url(tracked.page)
        if not url or url == "about:blank":
            return

        if url != tracked.last_url:
            self._handle_navigation(tracked, url)
        else:
            self._handle_standalone_triggers(tracked)

    def _handle_navigation(self, tracked: _TrackedPage, url: str) -> None:
        try:
            tracked.page.wait_for_timeout(NAV_SETTLE_MS)
        except Exception:
            pass

        settled_url = self._current_url(tracked.page) or url
        tracked.last_url = settled_url

        action = self._consume_pending_action(tracked.page) or dict(_FALLBACK_ACTION)
        self._capture_step(tracked, action)

    def _handle_standalone_triggers(self, tracked: _TrackedPage) -> None:
        triggers = self._drain_triggers(tracked.page)
        for action in triggers:
            if self._should_end:
                return
            self._capture_step(tracked, action)

    # -- JS-side channel consumption ----------------------------------------

    def _consume_pending_action(self, page: Page) -> Optional[Dict]:
        try:
            raw = page.evaluate("window.name")
        except Exception:
            return None
        if not raw:
            return None
        try:
            page.evaluate("window.name = ''")
        except Exception:
            pass
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return None

    def _drain_triggers(self, page: Page) -> List[Dict]:
        try:
            raw = page.evaluate(
                "(() => { const t = window.__dpaTriggers__ || []; window.__dpaTriggers__ = []; return t; })()"
            )
        except Exception:
            return []
        return raw or []

    def _drain_commands(self, page: Page) -> List[Dict]:
        try:
            raw = page.evaluate(
                "(() => { const c = window.__dpaCommands__ || []; window.__dpaCommands__ = []; return c; })()"
            )
        except Exception:
            return []
        return raw or []

    def _service_commands(self, tracked: _TrackedPage) -> None:
        for command in self._drain_commands(tracked.page):
            self._handle_command(command)

    def _handle_command(self, command: Dict) -> None:
        kind = command.get("type")
        if kind == "mark_goal_achieved":
            self._meta.goal_achieved = True
            print("  [overlay] goal marked achieved")
        elif kind == "abandon":
            self._meta.abandoned = True
            self._meta.goal_achieved = False
            print("  [overlay] session marked abandoned")
        elif kind == "add_note":
            note = (command.get("note") or "").strip()
            if note:
                self._meta.notes.append(note)
                print(f"  [overlay] note added: {note}")
        elif kind == "end_session":
            print("  [overlay] end session requested")
            self._should_end = True
            return
        else:
            return
        self._write_episode_meta()

    # -- step capture ----------------------------------------------------

    def _sync_overlay_step_count(self, page: Page) -> None:
        try:
            page.evaluate(f"window.__dpaSetStepCount__ && window.__dpaSetStepCount__({self._step_id})")
        except Exception:
            pass

    def _capture_step(self, tracked: _TrackedPage, action_raw: Dict) -> None:
        self._step_id += 1
        step_id = self._step_id
        timestamp = datetime.now(timezone.utc).isoformat()

        step = {
            "step_id": step_id,
            "timestamp": timestamp,
            "action": {
                "type": action_raw.get("type") or "unknown",
                "selector": action_raw.get("selector"),
                "bounding_box": action_raw.get("boundingBox"),
                "input_redacted": bool(action_raw.get("inputRedacted")),
            },
            # Raw, unmasked artifacts are never written to the episode
            # folder -- these two stay null for every step captured by
            # this recorder (see dom_snapshot_masked_path/
            # screenshot_masked_path below, and the module docstring).
            "screenshot_path": None,
            "screenshot_masked_path": None,
            "dom_snapshot_path": None,
            "dom_snapshot_masked_path": None,
            "network_events": [],
            "page_url_redacted": "",
            "viewport": MOBILE_VIEWPORT if self.device == "mobile" else DESKTOP_VIEWPORT,
            "capture_error": None,
            "tab_id": tracked.tab_id,
            "computed_styles_path": None,
        }

        # Capture order matches the spec: action (already built above),
        # screenshot, DOM, page URL, network -- each independently
        # try/excepted so one failure doesn't take the others down with it.
        errors: List[str] = []
        # Two independent, complementary signals get tallied into the same
        # redactions_applied list: this one is about the ACTION (the user
        # interacted with a field the overlay's own JS flagged sensitive,
        # see recorder/overlay.py); dom_masker's kinds below (e.g.
        # "password_field") are about the DOM STATE at capture time. They
        # are not a double-count of the same event.
        redaction_kinds: List[str] = ["action_on_sensitive_field"] if action_raw.get("inputRedacted") else []
        strict_abort = False

        raw_screenshot_path = os.path.join(self._raw_tmp_dir, f"step_{step_id:03d}_raw.png")
        screenshot_captured = False
        try:
            capture_screenshot(
                tracked.page, raw_screenshot_path, full_page=self.config.capture.screenshot_full_page
            )
            screenshot_captured = True
        except Exception as exc:
            errors.append(f"screenshot: {exc}")

        dom_html: Optional[str] = None
        try:
            dom_html = extract_dom(tracked.page)
        except Exception as exc:
            errors.append(f"dom: {exc}")

        boxes_to_black_out: List[Dict] = []
        if dom_html is not None:
            mask_result = mask_dom_for_step(tracked.page, dom_html, self._field_denylist)
            if mask_result.error:
                errors.append(f"dom_masking: {mask_result.error}")
            elif mask_result.residual_pii_found:
                self._meta.masking_issue_found = True
                errors.append("dom_masking: residual PII found in masked output -- artifact withheld")
                strict_abort = self.config.privacy.strict
            else:
                dom_filename = f"step_{step_id:03d}.html"
                dom_path = os.path.join(self.dom_dir, dom_filename)
                with open(dom_path, "w", encoding="utf-8") as f:
                    f.write(mask_result.masked_dom_html)
                step["dom_snapshot_masked_path"] = f"dom/{dom_filename}"
                redaction_kinds.extend(mask_result.dom_redaction_kinds)
                boxes_to_black_out = mask_result.boxes_to_black_out

        if screenshot_captured:
            masked_filename = f"step_{step_id:03d}_masked.png"
            masked_path = os.path.join(self.screenshots_dir, masked_filename)
            screenshot_error = mask_screenshot_for_step(raw_screenshot_path, masked_path, boxes_to_black_out)
            if screenshot_error:
                errors.append(f"screenshot_masking: {screenshot_error}")
            else:
                step["screenshot_masked_path"] = f"screenshots/{masked_filename}"

        # Computed CSS + geometry for interactive elements -- feeds
        # signals/visual_asymmetry.py. Button/link text isn't run through
        # the DOM masker: it's the same structurally-preserved category
        # (see recorder/masking/dom_masker.py's _is_structurally_allowlisted)
        # this recorder already treats as non-sensitive everywhere else.
        try:
            interactive_elements = capture_interactive_elements(tracked.page)
            styles_filename = f"step_{step_id:03d}.json"
            styles_path = os.path.join(self.computed_styles_dir, styles_filename)
            with open(styles_path, "w", encoding="utf-8") as f:
                json.dump(interactive_elements, f)
            step["computed_styles_path"] = f"computed_styles/{styles_filename}"
        except Exception as exc:
            errors.append(f"computed_styles: {exc}")

        try:
            step["page_url_redacted"] = redact_url(tracked.page.url, self._query_param_denylist)
        except Exception as exc:
            errors.append(f"url: {exc}")

        if tracked.network is not None:
            try:
                step["network_events"] = tracked.network.drain()
            except Exception as exc:
                errors.append(f"network: {exc}")

        if errors:
            step["capture_error"] = "; ".join(errors)

        if redaction_kinds:
            self._meta.redactions_applied.extend(tally_redactions(step_id, redaction_kinds))

        self._write_step_jsonl(step)
        self._meta.step_count = step_id
        self._write_episode_meta()
        self._sync_overlay_step_count(tracked.page)

        target_desc = step["action"].get("selector") or step["action"]["type"]
        print(f"  Step {step_id:>3} [{tracked.tab_id}] ({step['action']['type']:<8}) {target_desc}")

        if strict_abort:
            raise PrivacyValidationError(
                f"step {step_id}: masking self-check found residual PII and privacy.strict is true"
            )

    # -- durable writes ----------------------------------------------------

    def _write_step_jsonl(self, step: Dict) -> None:
        with open(self._steps_jsonl_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(step))
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())

    def _write_episode_meta(self) -> None:
        tmp_path = self._episode_meta_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self._meta.to_dict(), f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, self._episode_meta_path)

    # -- finalize ----------------------------------------------------

    def finalize(self) -> Dict:
        """Assembles the final schema-v2 episode.json from steps.jsonl +
        episode_meta.json. Safe to call after a clean end_session OR after
        a crash/interrupt -- it only ever reads back what's already
        durably on disk, never in-memory-only state."""
        self._meta.ended_at = datetime.now(timezone.utc).isoformat()
        self._write_episode_meta()
        steps = _read_steps_jsonl(self._steps_jsonl_path)
        return _write_final_episode(self.episode_dir, self._meta, steps, self.config)


def _read_steps_jsonl(steps_jsonl_path: str) -> List[Dict]:
    if not os.path.isfile(steps_jsonl_path):
        return []
    steps = []
    with open(steps_jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                steps.append(json.loads(line))
            except json.JSONDecodeError:
                # A partially-flushed final line from a hard crash -- skip
                # it rather than fail the whole finalize().
                continue
    return steps


def _write_final_episode(episode_dir: str, meta: _EpisodeMeta, steps: List[Dict], config: Config) -> Dict:
    episode_doc = {
        "schema_version": 2,
        "audit_metadata": {
            "audit_id": meta.episode_id,
            "target_domain": meta.site_domain,
            "audit_start_time": meta.started_at,
            "audit_end_time": meta.ended_at,
        },
        "website_context": {"domain": meta.site_domain, "industry": meta.sector},
        # This episode was captured natively as v2 -- there is no v1
        # pipeline run to report here, so these stay legitimately empty
        # rather than fabricated.
        "journey_steps": [],
        "temporal_checks": [],
        "disclosure_context": [],
        "episode": {
            "episode_id": meta.episode_id,
            "site_id": meta.site_domain,
            "site_domain": meta.site_domain,
            "sector": meta.sector,
            "goal": meta.goal_id,
            "revisit_index": meta.revisit_index,
            "device_context": meta.device_context,
            "locale": meta.locale,
            "paired_episode_id": meta.paired_episode_id,
            "collection_mode": "manual",
            "operator": meta.operator,
            # Set by journey/group_evidence_extractor.py, not here -- a
            # freshly finalized episode has never been through a group run
            # yet. Note finalize()/recover_incomplete_episode() always
            # rebuild this block from scratch, so re-running recover on an
            # already-grouped episode clears this back to null until
            # extract-group-evidence is re-run (cheap and idempotent).
            "group_evidence_path": None,
        },
        "steps": steps,
        "outcome": {
            "goal_achieved": meta.goal_achieved,
            "abandoned_reason": (meta.notes[-1] if (meta.abandoned and meta.notes) else None),
            "steps_to_complete": len(steps),
            # Price signal extraction is a Phase 2 "evidence" extractor
            # concern (see episode.evidence), not something this recorder
            # computes -- left null rather than guessed.
            "first_price_shown": None,
            "final_price_shown": None,
            "operator_notes": "; ".join(meta.notes),
        },
        "privacy": {
            "masker_version": MASKER_VERSION,
            "redactions_applied": list(meta.redactions_applied),
            "validation_passed": not meta.masking_issue_found,
        },
        "evidence": {},
        "attributes": {},
        "ccpa_verdict": {},
        "mechanism_verdict": {},
    }

    errors = validate_v2(episode_doc)
    if errors:
        # Logged only -- never written into episode_doc itself. Doing so
        # would (a) make the persisted/returned document lie about its own
        # shape (additionalProperties:false forbids this key) and (b) mean
        # a caller who re-validates what finalize() just returned/wrote
        # would see a DIFFERENT failure (the extra key) than the real one.
        print(f"  Warning: assembled episode.json failed v2 validation ({len(errors)} error(s)):")
        for error in errors:
            print(f"    - {error}")

    episode_path = os.path.join(episode_dir, EPISODE_FILENAME)
    with open(episode_path, "w", encoding="utf-8") as f:
        json.dump(episode_doc, f, indent=2)

    try:
        write_run_manifest(
            episode_dir=episode_dir, audit_id=meta.episode_id, config=config, operator=meta.operator
        )
    except Exception as exc:
        print(f"  Warning: could not write run_manifest.json: {exc}")

    print(f"Episode saved: {episode_path}")
    return episode_doc


def recover_incomplete_episode(episode_dir: str, config: Config) -> Dict:
    """Rebuilds episode.json for a session that crashed before finalize()
    ever ran, purely from what's already on disk (steps.jsonl +
    episode_meta.json) -- the resumability guarantee's read side."""
    meta_path = os.path.join(episode_dir, EPISODE_META_FILENAME)
    with open(meta_path, "r", encoding="utf-8") as f:
        meta_dict = json.load(f)
    meta = _EpisodeMeta(**meta_dict)
    meta.ended_at = meta.ended_at or datetime.now(timezone.utc).isoformat()

    steps_jsonl_path = os.path.join(episode_dir, STEPS_JSONL_FILENAME)
    steps = _read_steps_jsonl(steps_jsonl_path)
    return _write_final_episode(episode_dir, meta, steps, config)
