"""Raw DOM and visible-text extraction from a live Playwright page."""

from typing import List

from playwright.sync_api import Page

_VISIBLE_TEXT_JS = """
() => {
    const elements = Array.from(document.querySelectorAll('body *'));
    const texts = [];
    for (const el of elements) {
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') {
            continue;
        }
        const rect = el.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) {
            continue;
        }
        if (el.innerText) {
            texts.push(el.innerText);
        }
    }
    return texts.join('\\n');
}
"""

MAX_VISIBLE_TEXT_ITEMS = 200


def extract_dom(page: Page) -> str:
    return page.content()


def extract_visible_text(page: Page) -> List[str]:
    raw_text = page.evaluate(_VISIBLE_TEXT_JS)
    lines = [line.strip() for line in raw_text.split("\n") if line.strip()]
    deduped = list(dict.fromkeys(lines))
    if len(deduped) > MAX_VISIBLE_TEXT_ITEMS:
        deduped = deduped[: MAX_VISIBLE_TEXT_ITEMS - 1] + ["[truncated]"]
    return deduped
