"""The only masking-adjacent code that touches the live page (Layer 1).

Two small, read-only page.evaluate() calls:
  - form_field_metadata(): name/type/autocomplete/whether-a-value-is-
    present for every input/textarea/select on the page. Deliberately
    never reads or returns the actual field VALUE -- dom_masker.py only
    needs to know a sensitive field HAD something typed into it, not what,
    so a raw secret is never even transmitted out of the page's JS
    context, let alone into Python memory.
  - bounding_boxes_for_selectors(): document-relative {x,y,width,height}
    for a list of CSS selectors dom_masker.py already decided need
    redacting, used to black out the corresponding region of the
    screenshot (recorder/masking/screenshot_masker.py). Document-relative
    (rect + scroll offset), not viewport-relative, because full-page
    screenshots capture the whole scrollable page.
"""

from typing import Dict, List

from playwright.sync_api import Page

_FORM_FIELD_METADATA_JS = r"""
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

  function boundingBox(el) {
    try {
      const r = el.getBoundingClientRect();
      return { x: r.x + window.scrollX, y: r.y + window.scrollY, width: r.width, height: r.height };
    } catch (e) {
      return null;
    }
  }

  const fields = Array.from(document.querySelectorAll('input, textarea, select'));
  return fields.map((el) => ({
    selector: cssSelector(el),
    name: el.getAttribute('name') || '',
    id: el.id || '',
    type: (el.getAttribute('type') || el.tagName.toLowerCase()),
    autocomplete: el.getAttribute('autocomplete') || '',
    // Many real-world (esp. React-controlled) inputs carry no name/id at
    // all -- placeholder text ("Full name", "PIN code") is often the only
    // semantic signal available for the name/selector denylist check.
    placeholder: el.getAttribute('placeholder') || '',
    has_value: !!(el.value && String(el.value).length > 0),
    bounding_box: boundingBox(el),
  }));
}
"""

_BOUNDING_BOXES_JS = r"""
(selectors) => {
  const results = [];
  for (const selector of selectors) {
    let el = null;
    try {
      el = document.querySelector(selector);
    } catch (e) {
      continue;
    }
    if (!el) continue;
    try {
      const r = el.getBoundingClientRect();
      results.push({ x: r.x + window.scrollX, y: r.y + window.scrollY, width: r.width, height: r.height });
    } catch (e) {
      continue;
    }
  }
  return results;
}
"""


def form_field_metadata(page: Page) -> List[Dict]:
    try:
        return page.evaluate(_FORM_FIELD_METADATA_JS) or []
    except Exception:
        return []


def bounding_boxes_for_selectors(page: Page, selectors: List[str]) -> List[Dict]:
    if not selectors:
        return []
    try:
        return page.evaluate(_BOUNDING_BOXES_JS, selectors) or []
    except Exception:
        return []
