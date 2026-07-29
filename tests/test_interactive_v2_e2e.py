"""End-to-end test of recorder/interactive_v2.py against a real (headless,
for CI-friendliness -- production always launches headed) Playwright
browser and two local static HTML fixture pages.

No human is available in an automated test, so real Playwright actions
(click/fill+Tab/scroll/click) stand in for a human's browser interactions,
the same way scripts/audit_demo_site.py stands in for a human for the v1
recorder. recorder._poll_tick() is called directly instead of running the
blocking sleep loop, so the test is fast and deterministic rather than
racing a background thread.
"""

import json
import os
from unittest.mock import patch

import pytest
from PIL import Image

from config.settings import Config, PrivacyConfig
from journey.privacy import PrivacyValidationError
from journey.schema_migration import validate_v2
from recorder.interactive_v2 import EPISODE_FILENAME, InteractiveRecorderV2

PAGE1_HTML = """<!DOCTYPE html>
<html><body style="height:3000px;">
<button id="normal-btn" type="button">Click Me</button>
<br/>
<input id="text-input" type="text" name="search_query" />
<br/>
<input id="password-input" type="password" name="password" autocomplete="current-password" />
<br/>
<a id="nav-link" href="page2.html">Go to page 2</a>
<br/>
<a id="popup-link" target="_blank" href="page2.html">Open in new tab</a>
<br/>
<form id="test-form" action="page2.html" method="get">
  <input type="submit" id="submit-btn" value="Go" />
</form>
</body></html>
"""

PAGE2_HTML = "<!DOCTYPE html><html><body><h1>Page 2</h1></body></html>"

PII_PAGE_HTML = """<!DOCTYPE html>
<html><body>
<h1>Contact us</h1>
<p id="scarcity">Only 2 left in stock!</p>
<p id="contact">Email jane.doe@example.com or call 555-123-4567 for support.</p>
<input id="email-field" type="email" name="email" value="typed.value@example.com" />
</body></html>
"""


@pytest.fixture
def site_dir(tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    (site / "page1.html").write_text(PAGE1_HTML, encoding="utf-8")
    (site / "page2.html").write_text(PAGE2_HTML, encoding="utf-8")
    (site / "pii.html").write_text(PII_PAGE_HTML, encoding="utf-8")
    return site


@pytest.fixture
def recorder(tmp_path, site_dir):
    storage_dir = str(tmp_path / "storage")
    rec = InteractiveRecorderV2(
        storage_dir=storage_dir,
        episode_id="episode_test_001",
        site_url=(site_dir / "page1.html").as_uri(),
        site_domain="local-test-site",
        sector="ecommerce",
        goal_id="purchase_cheapest",
        goal_description="Find and complete purchase of the lowest-priced option.",
        operator="test-operator",
        config=Config(),
        revisit_index=0,
        device="desktop",
        locale=None,
        paired_episode_id=None,
    )
    main_page = rec.launch(headless=True)
    yield rec, main_page
    rec._teardown_browser()
    rec._cleanup_raw_artifacts()


def _make_recorder(tmp_path, site_dir, page_name, config=None):
    storage_dir = str(tmp_path / "storage")
    rec = InteractiveRecorderV2(
        storage_dir=storage_dir,
        episode_id="episode_pii_test",
        site_url=(site_dir / page_name).as_uri(),
        site_domain="local-test-site",
        sector="ecommerce",
        goal_id="purchase_cheapest",
        goal_description="Find and complete purchase of the lowest-priced option.",
        operator="test-operator",
        config=config or Config(),
        revisit_index=0,
        device="desktop",
        locale=None,
        paired_episode_id=None,
    )
    main_page = rec.launch(headless=True)
    return rec, main_page


def test_full_interaction_sequence_produces_a_valid_v2_episode(recorder):
    rec, page = recorder

    # 1. initial page load is itself step 1 (navigation from about:blank)
    rec._poll_tick()

    # 2. a normal, non-navigating click
    page.click("#normal-btn")
    rec._poll_tick()

    # 3. input commit on blur (Tab away), non-sensitive field
    page.fill("#text-input", "wireless mouse")
    page.keyboard.press("Tab")
    rec._poll_tick()

    # 4. input commit on a sensitive field -- must never carry the value
    page.fill("#password-input", "hunter2-super-secret")
    page.keyboard.press("Tab")
    rec._poll_tick()

    # 5. significant, debounced scroll
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(700)  # let the 500ms JS-side debounce settle
    rec._poll_tick()

    # 6. overlay commands: add a note, mark goal achieved
    page.evaluate(
        "document.querySelector('[data-dpa-btn=\"note\"]').click();"
        "document.getElementById('__dpa_note_input__').value = 'found item on sale';"
    )
    page.locator("#__dpa_note_input__").press("Enter")
    page.evaluate("document.querySelector('[data-dpa-btn=\"achieved\"]').click();")
    rec._poll_tick()

    # 7. a popup / new tab (must happen before #nav-link below navigates
    # the main tab away from page1.html, taking #popup-link with it)
    with page.expect_popup() as popup_info:
        page.click("#popup-link")
    popup = popup_info.value
    popup.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(300)
    rec._poll_tick()  # main page: nothing new
    rec._poll_tick()  # popup: its initial load becomes a step

    # 8. a click that leads to a real navigation
    page.click("#nav-link")
    rec._poll_tick()

    episode_doc = rec.finalize()

    # -- schema validity -------------------------------------------------
    errors = validate_v2(episode_doc)
    assert errors == [], f"episode failed v2 validation: {errors}"

    steps = episode_doc["steps"]
    step_types = [s["action"]["type"] for s in steps]

    assert "click" in step_types
    assert "input" in step_types
    assert "scroll" in step_types
    assert len(steps) >= 6

    # -- privacy: the sensitive field's value never appears anywhere -----
    dump = json.dumps(episode_doc)
    assert "hunter2-super-secret" not in dump

    input_steps = [s for s in steps if s["action"]["type"] == "input"]
    assert any(s["action"]["input_redacted"] is True for s in input_steps)
    assert any(s["action"]["input_redacted"] is False for s in input_steps)

    # -- multi-tab tracking ------------------------------------------------
    tab_ids = {s["tab_id"] for s in steps}
    assert "main" in tab_ids
    assert any(t.startswith("tab-") for t in tab_ids)

    # -- outcome / notes from overlay commands ------------------------------
    assert episode_doc["outcome"]["goal_achieved"] is True
    assert "found item on sale" in episode_doc["outcome"]["operator_notes"]

    # -- capture succeeded cleanly (no capture_error anywhere) --------------
    assert all(s["capture_error"] is None for s in steps)

    # -- raw artifacts are NEVER in the episode folder; masked ones are, and
    # actually landed on disk --------------------------------------------
    episode_dir = rec.episode_dir
    for step in steps:
        assert step["screenshot_path"] is None
        assert step["dom_snapshot_path"] is None
        if step["screenshot_masked_path"]:
            assert os.path.isfile(os.path.join(episode_dir, step["screenshot_masked_path"]))
        if step["dom_snapshot_masked_path"]:
            assert os.path.isfile(os.path.join(episode_dir, step["dom_snapshot_masked_path"]))

    for root, _dirs, files in os.walk(episode_dir):
        for name in files:
            assert "_raw" not in name, f"a raw-suffixed file leaked into the episode folder: {name}"

    # -- privacy block is real, not a placeholder ---------------------------
    assert episode_doc["privacy"]["masker_version"]
    assert episode_doc["privacy"]["validation_passed"] is True

    assert os.path.isfile(os.path.join(episode_dir, EPISODE_FILENAME))
    assert os.path.isfile(os.path.join(episode_dir, "run_manifest.json"))
    assert os.path.isfile(os.path.join(episode_dir, "steps.jsonl"))


def test_end_session_command_stops_the_poll_loop(recorder):
    rec, page = recorder
    rec._poll_tick()  # initial load

    page.evaluate("document.querySelector('[data-dpa-btn=\"end\"]').click();")
    rec._poll_tick()

    assert rec._should_end is True


def test_abandon_command_sets_outcome(recorder):
    rec, page = recorder
    rec._poll_tick()

    page.evaluate(
        "document.querySelector('[data-dpa-btn=\"note\"]').click();"
        "document.getElementById('__dpa_note_input__').value = 'could not find checkout button';"
    )
    page.locator("#__dpa_note_input__").press("Enter")
    page.evaluate("document.querySelector('[data-dpa-btn=\"abandon\"]').click();")
    rec._poll_tick()

    episode_doc = rec.finalize()
    assert episode_doc["outcome"]["goal_achieved"] is False
    assert episode_doc["outcome"]["abandoned_reason"] == "could not find checkout button"


def test_form_submit_is_captured_as_the_navigation_steps_action(recorder):
    rec, page = recorder
    rec._poll_tick()  # initial load

    page.click("#submit-btn")
    rec._poll_tick()

    episode_doc = rec.finalize()
    assert validate_v2(episode_doc) == []
    steps = episode_doc["steps"]
    assert steps[-1]["action"]["type"] == "submit"
    assert steps[-1]["action"]["selector"] is not None
    assert "page2.html" in steps[-1]["page_url_redacted"]


def test_screenshot_failure_is_recorded_as_capture_error_not_dropped(recorder):
    rec, page = recorder
    rec._poll_tick()  # initial load (succeeds)

    with patch("recorder.interactive_v2.capture_screenshot", side_effect=RuntimeError("boom: no display")):
        page.click("#normal-btn")
        rec._poll_tick()

    episode_doc = rec.finalize()
    steps = episode_doc["steps"]
    assert len(steps) == 2

    failed_step = steps[-1]
    # The step exists (not dropped) and carries a clear capture_error...
    assert failed_step["capture_error"] is not None
    assert "boom: no display" in failed_step["capture_error"]
    assert failed_step["screenshot_path"] is None
    assert failed_step["screenshot_masked_path"] is None
    # ...but DOM capture+masking, which didn't fail, still succeeded independently.
    assert failed_step["dom_snapshot_path"] is None  # raw DOM is never persisted, by design
    assert failed_step["dom_snapshot_masked_path"] is not None
    assert os.path.isfile(os.path.join(rec.episode_dir, failed_step["dom_snapshot_masked_path"]))

    # A step with a capture_error still has to validate against the schema
    # -- capture_error is documented as nullable, not a special case.
    assert validate_v2(episode_doc) == []


def test_overlay_survives_navigation_without_manual_reinjection(recorder):
    rec, page = recorder
    rec._poll_tick()

    page.click("#nav-link")
    rec._poll_tick()

    # No code here re-injects anything -- Playwright's add_init_script
    # re-ran on its own for the new document, per how it was registered
    # once in _attach_page().
    assert page.evaluate("!!document.getElementById('__dpa_overlay__')") is True
    assert page.evaluate("window.__dpaInitialized__") is True


# -- masking-specific end-to-end coverage ------------------------------


def test_pii_is_redacted_from_dom_and_screenshot_is_black_boxed(tmp_path, site_dir):
    rec, page = _make_recorder(tmp_path, site_dir, "pii.html")
    try:
        rec._poll_tick()
        episode_doc = rec.finalize()
    finally:
        rec._teardown_browser()
        rec._cleanup_raw_artifacts()

    assert validate_v2(episode_doc) == []
    step = episode_doc["steps"][0]

    # -- DOM: PII gone, replaced by typed placeholders; scarcity text kept --
    dom_path = os.path.join(rec.episode_dir, step["dom_snapshot_masked_path"])
    with open(dom_path, "r", encoding="utf-8") as f:
        masked_dom = f.read()
    assert "jane.doe@example.com" not in masked_dom
    assert "555-123-4567" not in masked_dom
    assert "typed.value@example.com" not in masked_dom
    assert "[EMAIL]" in masked_dom
    assert "[PHONE]" in masked_dom
    assert "Only 2 left in stock!" in masked_dom  # allowlisted, untouched

    # -- raw screenshot never in the episode folder; masked one is ---------
    assert step["screenshot_path"] is None
    screenshot_path = os.path.join(rec.episode_dir, step["screenshot_masked_path"])
    assert os.path.isfile(screenshot_path)

    # -- the masked screenshot actually has black-boxed regions, not just
    # an untouched copy of the original -- at least one pixel is pure
    # black where the redacted contact paragraph was.
    image = Image.open(screenshot_path).convert("RGB")
    has_black_pixel = any(
        image.getpixel((x, y)) == (0, 0, 0)
        for x in range(0, image.width, 5)
        for y in range(0, min(image.height, 400), 5)
    )
    assert has_black_pixel, "expected at least one black-boxed region near the top of the page"

    # -- redactions_applied is populated with real, specific kinds --------
    kinds = {r["kind"] for r in episode_doc["privacy"]["redactions_applied"]}
    assert "email" in kinds
    assert "phone" in kinds
    assert "email_field" in kinds
    assert episode_doc["privacy"]["masker_version"]
    assert episode_doc["privacy"]["validation_passed"] is True


def test_strict_mode_aborts_session_on_residual_pii(tmp_path, site_dir):
    strict_config = Config(privacy=PrivacyConfig(enabled=True, strict=True))
    rec, page = _make_recorder(tmp_path, site_dir, "pii.html", config=strict_config)
    try:
        with patch("recorder.masking.masker.residual_pii_found", return_value=True):
            with pytest.raises(PrivacyValidationError):
                rec._poll_tick()
    finally:
        rec._teardown_browser()
        rec._cleanup_raw_artifacts()

    # Even though the session aborted, finalize() still produces a valid
    # (if minimal) episode from whatever was durably captured, and
    # validation_passed correctly reflects the problem.
    episode_doc = rec.finalize()
    assert episode_doc["privacy"]["validation_passed"] is False
    assert episode_doc["steps"][0]["capture_error"] is not None
    assert episode_doc["steps"][0]["dom_snapshot_masked_path"] is None
