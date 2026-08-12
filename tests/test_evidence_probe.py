"""Tests for recorder/evidence_probe.py -- the only recorder code that
captures computed CSS/geometry for interactive elements. Real headless
Playwright, no mocks: this is a single page.evaluate() call, trivial
enough in isolation that a fake Page object would just be re-testing the
fake, not the real extraction.
"""

import pytest
from playwright.sync_api import sync_playwright

from recorder.evidence_probe import capture_interactive_elements

PAGE_HTML = """<!DOCTYPE html>
<html><body>
<button id="text-btn">Cancel my plan</button>
<button id="icon-close" aria-label="Close"><svg></svg></button>
<button id="no-label"><svg></svg></button>
<a id="text-and-aria" aria-label="Close this dialog">×</a>
</body></html>
"""


@pytest.fixture
def page():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        pg = browser.new_page()
        pg.set_content(PAGE_HTML)
        yield pg
        browser.close()


def _by_selector(elements, selector):
    return next(el for el in elements if el["selector"] == selector)


def test_text_button_has_its_own_text_and_no_aria_label(page):
    elements = capture_interactive_elements(page)
    el = _by_selector(elements, "#text-btn")
    assert el["text"] == "Cancel my plan"
    assert el["aria_label"] == ""


def test_icon_only_button_has_empty_text_but_captures_aria_label(page):
    elements = capture_interactive_elements(page)
    el = _by_selector(elements, "#icon-close")
    assert el["text"] == ""
    assert el["aria_label"] == "Close"


def test_icon_only_button_with_no_aria_label_has_both_empty(page):
    elements = capture_interactive_elements(page)
    el = _by_selector(elements, "#no-label")
    assert el["text"] == ""
    assert el["aria_label"] == ""


def test_element_with_both_text_and_aria_label_captures_both_independently(page):
    # signals/stated_vs_actual.py decides which one to prefer -- this
    # layer just reports what's actually on the element, unfiltered.
    elements = capture_interactive_elements(page)
    el = _by_selector(elements, "#text-and-aria")
    assert el["text"] == "×"
    assert el["aria_label"] == "Close this dialog"
