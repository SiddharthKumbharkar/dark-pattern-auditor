"""Captures computed CSS + geometry for interactive elements (Layer 1).

Extends the recorder specifically for signals/visual_asymmetry.py, which
needs computed (post-stylesheet) color/font-size/position data that plain
DOM HTML never carries (inline styles and classes don't tell you what a
browser actually rendered). Written once per step to computed_styles/
alongside screenshots/ and dom/, so the evidence extractor
(journey/evidence_extractor.py) can compute everything from the stored
episode alone, with no live page involved -- this file is the only place
in the whole evidence-extraction path that touches Playwright.
"""

from typing import Dict, List

from playwright.sync_api import Page

_INTERACTIVE_ELEMENTS_JS = r"""
() => {
  function cssSelector(el) {
    if (!el || el.nodeType !== 1) return null;
    if (el.id) return '#' + el.id;
    const parts = [];
    let node = el;
    let depth = 0;
    while (node && node.nodeType === 1 && depth < 4) {
      let part = node.tagName.toLowerCase();
      if (node.classList && node.classList.length) {
        part += '.' + Array.from(node.classList).slice(0, 2).join('.');
      } else if (node.parentElement) {
        const siblings = Array.from(node.parentElement.children).filter((c) => c.tagName === node.tagName);
        if (siblings.length > 1) part += ':nth-of-type(' + (siblings.indexOf(node) + 1) + ')';
      }
      parts.unshift(part);
      node = node.parentElement;
      depth += 1;
    }
    return parts.join(' > ');
  }

  const selector = 'button, a, input[type="submit"], input[type="button"], ' +
    '[role="button"], input[type="checkbox"], input[type="radio"]';
  const elements = Array.from(document.querySelectorAll(selector));

  return elements.map((el, index) => {
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    const text = ((el.innerText || el.value) || '').trim().slice(0, 100);
    return {
      selector: cssSelector(el),
      tag: el.tagName.toLowerCase(),
      role: el.getAttribute('role') || '',
      text: text,
      dom_order: index,
      tab_index: el.tabIndex,
      // document-relative, matching the full-page screenshot's pixel
      // space (see recorder/masking/browser_probe.py's identical convention).
      bounding_box: { x: rect.x + window.scrollX, y: rect.y + window.scrollY, width: rect.width, height: rect.height },
      color: style.color,
      background_color: style.backgroundColor,
      font_size_px: parseFloat(style.fontSize) || null,
      // Viewport-relative (NOT scroll-adjusted): true if the element was
      // outside the visible area at the moment of capture, i.e. what the
      // screenshot's "fold" actually was for this step.
      is_below_fold: rect.top >= window.innerHeight,
    };
  });
}
"""


def capture_interactive_elements(page: Page) -> List[Dict]:
    try:
        return page.evaluate(_INTERACTIVE_ELEMENTS_JS) or []
    except Exception:
        return []
