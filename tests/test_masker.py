"""Tests for recorder/masking/masker.py -- the orchestrator that ties
dom_masker + screenshot_masker + browser_probe together, and the ONLY
place recorder/interactive_v2.py calls into recorder/masking/. Real
headless Playwright for the page-touching paths (mask_dom_for_step),
real generated PNGs for the screenshot path -- no mocks.
"""

import os

import pytest
from playwright.sync_api import sync_playwright
from PIL import Image

from recorder.masking.masker import (
    MASKER_VERSION,
    StepMaskResult,
    mask_dom_for_step,
    mask_screenshot_for_step,
    residual_pii_found,
)

FORM_PAGE_HTML = """<!DOCTYPE html>
<html><body>
<h1>Checkout</h1>
<input name="email" type="email" value="jane@example.com">
<input name="pwd" type="password" value="hunter2">
<p>Only 2 left in stock!</p>
<button type="button">Continue</button>
</body></html>
"""


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


@pytest.fixture
def page(browser):
    pg = browser.new_page()
    pg.set_content(FORM_PAGE_HTML)
    yield pg
    pg.close()


# -- residual_pii_found: the strict-mode self-check -----------------------


def test_residual_pii_found_true_for_leaked_email():
    assert residual_pii_found("<p>Contact jane@example.com</p>") is True


def test_residual_pii_found_true_for_leaked_card_number():
    assert residual_pii_found("<p>4111 1111 1111 1111</p>") is True


def test_residual_pii_found_true_for_leaked_phone():
    assert residual_pii_found("<p>Call 555-123-4567</p>") is True


def test_residual_pii_found_false_for_properly_masked_html():
    assert residual_pii_found("<p>Contact [EMAIL] or call [PHONE]</p>") is False


def test_residual_pii_found_false_for_clean_html_with_no_pii():
    assert residual_pii_found("<p>Only 2 left in stock! Rs. 899</p>") is False


def test_residual_pii_found_false_for_empty_or_none():
    assert residual_pii_found("") is False
    assert residual_pii_found(None) is False


def test_residual_pii_found_strips_tags_before_scanning():
    # A card number split across attributes vs text content -- the scan is
    # text-only (BeautifulSoup get_text), so this checks it still catches
    # PII sitting in ordinary rendered text even amid markup noise.
    html = '<div class="a"><span class="b">Card ending in</span> 4111111111111111</div>'
    assert residual_pii_found(html) is True


# -- mask_dom_for_step: the real orchestration, real page ------------------


def test_mask_dom_for_step_redacts_password_field_and_preserves_scarcity_copy(page):
    result = mask_dom_for_step(page, FORM_PAGE_HTML)
    assert isinstance(result, StepMaskResult)
    assert result.error is None
    assert "hunter2" not in result.masked_dom_html
    assert "Only 2 left in stock!" in result.masked_dom_html


def test_mask_dom_for_step_redacts_email_field(page):
    result = mask_dom_for_step(page, FORM_PAGE_HTML)
    assert "jane@example.com" not in result.masked_dom_html


def test_mask_dom_for_step_reports_redaction_kinds(page):
    result = mask_dom_for_step(page, FORM_PAGE_HTML)
    assert "password_field" in result.dom_redaction_kinds
    assert "email_field" in result.dom_redaction_kinds


def test_mask_dom_for_step_produces_boxes_to_black_out_for_redacted_fields(page):
    result = mask_dom_for_step(page, FORM_PAGE_HTML)
    assert len(result.boxes_to_black_out) >= 2  # email field + password field
    for box in result.boxes_to_black_out:
        for key in ("x", "y", "width", "height"):
            assert key in box


def test_mask_dom_for_step_residual_pii_found_is_false_when_masking_worked(page):
    result = mask_dom_for_step(page, FORM_PAGE_HTML)
    assert result.residual_pii_found is False


def test_mask_dom_for_step_clean_page_has_no_redactions(browser):
    clean_html = "<html><body><p>Only 2 left in stock!</p><button>Buy</button></body></html>"
    pg = browser.new_page()
    try:
        pg.set_content(clean_html)
        result = mask_dom_for_step(pg, clean_html)
        assert result.error is None
        assert result.dom_redaction_kinds == []
        assert result.boxes_to_black_out == []
        assert "Only 2 left in stock!" in result.masked_dom_html
    finally:
        pg.close()


def test_mask_dom_for_step_respects_custom_field_denylist(browser):
    # Full document, matching what the live page actually renders (a bare
    # fragment would make BeautifulSoup's parsed tree diverge from the
    # live page's, so the selector browser_probe.py generates from the
    # live DOM wouldn't resolve against the string dom_masker.py parses).
    html = "<html><body><input name=\"custom_secret\" type=\"text\" value=\"shh\"></body></html>"
    pg = browser.new_page()
    try:
        pg.set_content(html)
        result = mask_dom_for_step(pg, html, field_denylist=["custom_secret"])
        assert result.error is None
        assert "[REDACTED:custom_secret]" in result.masked_dom_html
        assert "sensitive_field" in result.dom_redaction_kinds
    finally:
        pg.close()


def test_mask_dom_for_step_captures_exception_as_error_not_a_crash(page, monkeypatch):
    # form_field_metadata() and bounding_boxes_for_selectors() already
    # swallow their own exceptions internally (see browser_probe.py), so a
    # page.evaluate() failure never actually reaches mask_dom_for_step's
    # own try/except -- what CAN reach it is a bug in mask_dom_html()
    # itself (e.g. a malformed selector raising from soupsieve). Forcing
    # that specific call to raise is the direct way to exercise this
    # module's own error-capture, not a fake Page standing in for a real one.
    import recorder.masking.masker as masker_module

    def _boom(*args, **kwargs):
        raise RuntimeError("dom_masker exploded")

    monkeypatch.setattr(masker_module, "mask_dom_html", _boom)
    result = mask_dom_for_step(page, FORM_PAGE_HTML)
    assert result.error is not None
    assert "dom_masker exploded" in result.error
    assert result.masked_dom_html is None


# -- mask_screenshot_for_step ------------------------------------------------


def test_mask_screenshot_for_step_draws_boxes_and_returns_none_on_success(tmp_path):
    src = os.path.join(str(tmp_path), "src.png")
    out = os.path.join(str(tmp_path), "out.png")
    Image.new("RGB", (100, 100), color="white").save(src)

    error = mask_screenshot_for_step(src, out, [{"x": 10, "y": 10, "width": 20, "height": 20}])
    assert error is None
    image = Image.open(out).convert("RGB")
    assert image.getpixel((15, 15)) == (0, 0, 0)


def test_mask_screenshot_for_step_no_boxes_still_succeeds(tmp_path):
    src = os.path.join(str(tmp_path), "src.png")
    out = os.path.join(str(tmp_path), "out.png")
    Image.new("RGB", (50, 50), color="white").save(src)

    error = mask_screenshot_for_step(src, out, [])
    assert error is None
    assert os.path.isfile(out)


def test_mask_screenshot_for_step_missing_source_file_returns_error_string(tmp_path):
    error = mask_screenshot_for_step(
        os.path.join(str(tmp_path), "does_not_exist.png"),
        os.path.join(str(tmp_path), "out.png"),
        [],
    )
    assert error is not None
    assert isinstance(error, str)


# -- module identity ------------------------------------------------------


def test_masker_version_is_a_non_empty_string():
    assert isinstance(MASKER_VERSION, str)
    assert MASKER_VERSION
