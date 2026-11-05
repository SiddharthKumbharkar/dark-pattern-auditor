"""Tests for recorder/masking/browser_probe.py -- the only masking-adjacent
code that touches a live page. Real headless Playwright, no mocks: these
two page.evaluate() calls are trivial enough in isolation that a fake
Page object would just be re-testing the fake, not the real extraction.
"""

import pytest
from playwright.sync_api import sync_playwright

from recorder.masking.browser_probe import bounding_boxes_for_selectors, form_field_metadata

FORM_HTML = """<!DOCTYPE html>
<html><body>
<input id="email-field" name="email" type="email" autocomplete="email" value="jane@example.com">
<input name="quantity" type="number" value="3">
<input type="password" name="pwd" value="hunter2">
<textarea name="notes" placeholder="Special instructions"></textarea>
<input name="unfilled" type="text">
<div id="promo" style="position:absolute; left:20px; top:30px; width:100px; height:40px;">Sale</div>
</body></html>
"""


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


@pytest.fixture(scope="module")
def page(browser):
    pg = browser.new_page()
    pg.set_content(FORM_HTML)
    yield pg
    pg.close()


# -- form_field_metadata: must never leak the actual value ------------------


def test_form_field_metadata_never_includes_the_raw_value(page):
    fields = form_field_metadata(page)
    blob = str(fields)
    assert "jane@example.com" not in blob
    assert "hunter2" not in blob


def test_form_field_metadata_reports_name_type_autocomplete(page):
    fields = form_field_metadata(page)
    email_field = next(f for f in fields if f["name"] == "email")
    assert email_field["type"] == "email"
    assert email_field["autocomplete"] == "email"
    assert email_field["id"] == "email-field"
    assert email_field["selector"] == "#email-field"


def test_form_field_metadata_has_value_is_true_for_filled_field(page):
    fields = form_field_metadata(page)
    email_field = next(f for f in fields if f["name"] == "email")
    assert email_field["has_value"] is True


def test_form_field_metadata_has_value_is_false_for_empty_field(page):
    fields = form_field_metadata(page)
    unfilled = next(f for f in fields if f["name"] == "unfilled")
    assert unfilled["has_value"] is False


def test_form_field_metadata_captures_placeholder_for_unnamed_semantic_hint(page):
    fields = form_field_metadata(page)
    notes = next(f for f in fields if f["name"] == "notes")
    assert notes["placeholder"] == "Special instructions"


def test_form_field_metadata_covers_every_field_on_the_page(page):
    fields = form_field_metadata(page)
    names = {f["name"] for f in fields}
    assert names == {"email", "quantity", "pwd", "notes", "unfilled"}


def test_form_field_metadata_includes_bounding_box(page):
    fields = form_field_metadata(page)
    email_field = next(f for f in fields if f["name"] == "email")
    assert email_field["bounding_box"] is not None
    for key in ("x", "y", "width", "height"):
        assert key in email_field["bounding_box"]


def test_form_field_metadata_empty_page_returns_empty_list(browser):
    # A second page off the module-scoped browser fixture -- nesting a
    # second `with sync_playwright()` here would conflict with the one
    # the fixture already has open.
    blank = browser.new_page()
    try:
        blank.set_content("<html><body><p>No form here</p></body></html>")
        assert form_field_metadata(blank) == []
    finally:
        blank.close()


# -- bounding_boxes_for_selectors --------------------------------------------


def test_bounding_boxes_for_selectors_returns_document_relative_coordinates(page):
    boxes = bounding_boxes_for_selectors(page, ["#promo"])
    assert len(boxes) == 1
    box = boxes[0]
    assert box["x"] == pytest.approx(20, abs=2)
    assert box["y"] == pytest.approx(30, abs=2)
    assert box["width"] == pytest.approx(100, abs=2)
    assert box["height"] == pytest.approx(40, abs=2)


def test_bounding_boxes_for_selectors_skips_nonexistent_selector(page):
    boxes = bounding_boxes_for_selectors(page, ["#does-not-exist"])
    assert boxes == []


def test_bounding_boxes_for_selectors_handles_mixed_valid_and_invalid(page):
    boxes = bounding_boxes_for_selectors(page, ["#does-not-exist", "#promo"])
    assert len(boxes) == 1


def test_bounding_boxes_for_selectors_empty_list_returns_empty(page):
    assert bounding_boxes_for_selectors(page, []) == []


def test_bounding_boxes_for_selectors_multiple_real_selectors(page):
    boxes = bounding_boxes_for_selectors(page, ["#promo", "#email-field"])
    assert len(boxes) == 2
