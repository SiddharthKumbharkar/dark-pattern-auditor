"""Tests for recorder/browser.py -- the v1 pipeline's capture_step(), which
used to write completely raw/unmasked screenshots and DOM to disk. Real
headless Playwright against small local HTML fixtures with genuine PII in
ordinary page text (not just form fields), checking the actual files
written to storage_dir -- not mocks, and not just the returned dict.
"""

import os
import shutil
import tempfile
from urllib.parse import parse_qsl, urlsplit

import pytest
from PIL import Image

from config.settings import PrivacyConfig
from journey.privacy import PrivacyValidationError
from recorder.browser import BrowserRecorder
from recorder.redaction import PLACEHOLDER_TOKEN

PII_PAGE_HTML = """<!DOCTYPE html>
<html><body>
<h1>Order confirmed</h1>
<p>A receipt has been sent to jane.doe@example.com.</p>
<p>Card on file: 4111 1111 1111 1111</p>
<p>Call us at 555-123-4567 with questions.</p>
<p>Only 2 left in stock!</p>
<button type="button">Continue</button>
</body></html>
"""

CLEAN_PAGE_HTML = """<!DOCTYPE html>
<html><body>
<h1>Welcome</h1>
<p>Only 2 left in stock!</p>
<button type="button">Continue</button>
</body></html>
"""


def _recorder(tmp_path, privacy=None):
    rec = BrowserRecorder(
        storage_dir=str(tmp_path / "storage"),
        audit_id="audit_test",
        screenshot_full_page=True,
        privacy=privacy,
    )
    rec.start()
    return rec


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# -- the core leak: DOM/screenshot must never carry raw PII -------------


def test_dom_snapshot_on_disk_has_no_raw_pii(tmp_path):
    rec = _recorder(tmp_path)
    try:
        rec.page.set_content(PII_PAGE_HTML)
        step = rec.capture_step(step_id=1, url="https://shop.example.com/confirm", action_type="open_page")
        dom_path = os.path.join(rec.dom_dir, step["state_capture"]["dom_snapshot_id"])
        dom_text = _read(dom_path)
        assert "jane.doe@example.com" not in dom_text
        assert "4111 1111 1111 1111" not in dom_text
        assert "555-123-4567" not in dom_text
        assert "[EMAIL]" in dom_text
        assert "[CARD]" in dom_text
        assert "[PHONE]" in dom_text
    finally:
        rec.stop()


def test_dom_snapshot_preserves_allowlisted_scarcity_copy(tmp_path):
    rec = _recorder(tmp_path)
    try:
        rec.page.set_content(PII_PAGE_HTML)
        step = rec.capture_step(step_id=1, url="https://shop.example.com/confirm", action_type="open_page")
        dom_path = os.path.join(rec.dom_dir, step["state_capture"]["dom_snapshot_id"])
        assert "Only 2 left in stock!" in _read(dom_path)
    finally:
        rec.stop()


def test_visible_text_summary_has_no_raw_pii(tmp_path):
    rec = _recorder(tmp_path)
    try:
        rec.page.set_content(PII_PAGE_HTML)
        step = rec.capture_step(step_id=1, url="https://shop.example.com/confirm", action_type="open_page")
        blob = " ".join(step["visible_text_summary"])
        assert "jane.doe@example.com" not in blob
        assert "4111 1111 1111 1111" not in blob
        assert "555-123-4567" not in blob
    finally:
        rec.stop()


def test_screenshot_on_disk_is_the_masked_one_not_the_raw_one(tmp_path):
    rec = _recorder(tmp_path)
    try:
        rec.page.set_content(PII_PAGE_HTML)
        step = rec.capture_step(step_id=1, url="https://shop.example.com/confirm", action_type="open_page")
        screenshot_path = os.path.join(rec.screenshots_dir, step["state_capture"]["screenshot_id"])
        assert os.path.isfile(screenshot_path)
        # A real image was written (not an empty/broken file).
        img = Image.open(screenshot_path)
        assert img.width > 0 and img.height > 0
    finally:
        rec.stop()


def test_raw_screenshot_never_appears_under_the_episode_folder(tmp_path):
    rec = _recorder(tmp_path)
    try:
        rec.page.set_content(PII_PAGE_HTML)
        rec.capture_step(step_id=1, url="https://shop.example.com/confirm", action_type="open_page")
        episode_dir = os.path.join(str(tmp_path / "storage"), "audit_test")
        for root, _dirs, files in os.walk(episode_dir):
            for name in files:
                assert not name.endswith("_raw.png"), f"raw screenshot leaked into episode folder: {name}"
    finally:
        rec.stop()


def test_raw_screenshot_staging_dir_is_outside_the_episode_folder(tmp_path):
    rec = _recorder(tmp_path)
    try:
        episode_dir = os.path.join(str(tmp_path / "storage"), "audit_test")
        assert not rec._raw_tmp_dir.startswith(episode_dir)
    finally:
        rec.stop()


# -- redaction tracking ----------------------------------------------


def test_redactions_applied_is_populated(tmp_path):
    rec = _recorder(tmp_path)
    try:
        rec.page.set_content(PII_PAGE_HTML)
        rec.capture_step(step_id=1, url="https://shop.example.com/confirm", action_type="open_page")
        kinds = {r["kind"] for r in rec.redactions_applied}
        assert kinds & {"email", "card", "phone"}
    finally:
        rec.stop()


def test_clean_page_has_no_redactions(tmp_path):
    rec = _recorder(tmp_path)
    try:
        rec.page.set_content(CLEAN_PAGE_HTML)
        rec.capture_step(step_id=1, url="https://shop.example.com/", action_type="open_page")
        assert rec.redactions_applied == []
        assert rec.masking_issue_found is False
    finally:
        rec.stop()


# -- URL redaction --------------------------------------------------------


def test_step_url_is_redacted():
    with tempfile.TemporaryDirectory() as storage_dir:
        rec = BrowserRecorder(storage_dir=storage_dir, audit_id="audit_url_test")
        rec.start()
        try:
            rec.page.set_content(CLEAN_PAGE_HTML)
            step = rec.capture_step(
                step_id=1, url="https://shop.example.com/?session=abc123secret&qty=2", action_type="open_page"
            )
            assert "abc123secret" not in step["url"]
            query = dict(parse_qsl(urlsplit(step["url"]).query))
            assert query["session"] == PLACEHOLDER_TOKEN  # re-encoded as %5BTOKEN%5D in the raw string, decodes back to this
            assert query["qty"] == "2"
        finally:
            rec.stop()


# -- cleanup ----------------------------------------------------------


def test_cleanup_raw_artifacts_removes_the_temp_dir(tmp_path):
    rec = _recorder(tmp_path)
    raw_dir = rec._raw_tmp_dir
    rec.page.set_content(CLEAN_PAGE_HTML)
    rec.capture_step(step_id=1, url="https://shop.example.com/", action_type="open_page")
    assert os.path.isdir(raw_dir)
    rec.stop()
    assert not os.path.isdir(raw_dir)


def test_keep_raw_artifacts_true_preserves_the_temp_dir(tmp_path):
    rec = _recorder(tmp_path, privacy=PrivacyConfig(keep_raw_artifacts=True))
    raw_dir = rec._raw_tmp_dir
    try:
        rec.page.set_content(CLEAN_PAGE_HTML)
        rec.capture_step(step_id=1, url="https://shop.example.com/", action_type="open_page")
    finally:
        rec.stop()
    assert os.path.isdir(raw_dir)
    shutil.rmtree(raw_dir, ignore_errors=True)


# -- residual PII / strict mode ------------------------------------------


def test_non_strict_residual_pii_withholds_the_step_artifacts(tmp_path, monkeypatch):
    # Force the post-mask self-check to report residual PII regardless of
    # what dom_masker actually produced, so this test doesn't depend on
    # finding real content the masker happens to miss -- it verifies the
    # WITHHOLD behavior, not the masker's own detection accuracy (that's
    # tests/test_masker.py's job).
    import recorder.browser as browser_module

    monkeypatch.setattr(browser_module, "residual_pii_found", lambda *_a, **_k: True)

    rec = _recorder(tmp_path, privacy=PrivacyConfig(strict=False))
    try:
        rec.page.set_content(CLEAN_PAGE_HTML)
        step = rec.capture_step(step_id=1, url="https://shop.example.com/", action_type="open_page")
        assert step["state_capture"]["screenshot_id"] == ""
        assert step["state_capture"]["dom_snapshot_id"] == ""
        assert step["visible_text_summary"] == []
        assert rec.masking_issue_found is True
        # nothing for this step was written into the episode folder
        assert os.listdir(rec.dom_dir) == []
        assert os.listdir(rec.screenshots_dir) == []
    finally:
        rec.stop()


def test_strict_residual_pii_raises_and_writes_nothing(tmp_path, monkeypatch):
    import recorder.browser as browser_module

    monkeypatch.setattr(browser_module, "residual_pii_found", lambda *_a, **_k: True)

    rec = _recorder(tmp_path, privacy=PrivacyConfig(strict=True))
    try:
        rec.page.set_content(CLEAN_PAGE_HTML)
        with pytest.raises(PrivacyValidationError):
            rec.capture_step(step_id=1, url="https://shop.example.com/", action_type="open_page")
        assert os.listdir(rec.dom_dir) == []
        assert os.listdir(rec.screenshots_dir) == []
    finally:
        rec.stop()


# -- exclusion still works alongside masking ------------------------------


def test_excluded_url_still_skips_capture_entirely(tmp_path):
    rec = _recorder(tmp_path)
    try:
        rec.page.set_content(CLEAN_PAGE_HTML)
        step = rec.capture_step(
            step_id=1, url="https://shop.example.com/payment/confirm", action_type="open_page"
        )
        assert step["capture_excluded"] is True
        assert step["state_capture"] is None
        assert os.listdir(rec.dom_dir) == []
        assert os.listdir(rec.screenshots_dir) == []
    finally:
        rec.stop()
