"""Shared per-element text/structure extraction from DOM HTML (Layer 3).

Pure functions: no Playwright, no file I/O, no LLM calls. Several evidence
signals (claims, price_drift, complexity, path_deviation, friction) each
need "text with a selector" or "does this page have X kind of element"
from the same masked DOM string, so that extraction lives here once
instead of five times.
"""

import re
from typing import Dict, List, Optional

from bs4 import BeautifulSoup, NavigableString

_INTERSTITIAL_KEYWORDS = ["modal", "dialog", "popup", "confirm", "overlay"]
_INTERACTIVE_SELECTOR = 'button, a, input, select, textarea, [role="button"]'


def css_selector(tag) -> Optional[str]:
    """Public (not module-private) because more than one signal now needs
    to compute a selector for an arbitrary bs4 tag it found by walking the
    DOM directly, rather than one already handed to it with a selector
    attached -- see signals/ui_regions.py's disclosure-element tagging,
    which resolves a selector for an element recorder/evidence_probe.py's
    interactive-elements-only capture never saw in the first place."""
    if tag is None or not getattr(tag, "name", None):
        return None
    if tag.get("id"):
        return f"#{tag['id']}"
    parts: List[str] = []
    node = tag
    depth = 0
    while node is not None and getattr(node, "name", None) and depth < 4:
        part = node.name
        classes = node.get("class") or []
        if classes:
            part += "." + ".".join(classes[:2])
        else:
            parent = node.parent
            if parent is not None and hasattr(parent, "find_all"):
                siblings = parent.find_all(node.name, recursive=False)
                if len(siblings) > 1:
                    part += f":nth-of-type({siblings.index(node) + 1})"
        parts.insert(0, part)
        node = node.parent
        depth += 1
    return " > ".join(parts)


def extract_text_candidates(dom_html: str) -> List[Dict]:
    """[{"text": str, "selector": str}] for every non-empty text node's
    OWN text (not concatenated with descendants), skipping script/style."""
    soup = BeautifulSoup(dom_html or "", "html.parser")
    results = []
    for node in soup.find_all(string=True):
        if not isinstance(node, NavigableString) or not node.strip():
            continue
        parent = node.parent
        if parent is None or parent.name in ("script", "style"):
            continue
        results.append({"text": node.strip(), "selector": css_selector(parent)})
    return results


def full_text(dom_html: str) -> str:
    return BeautifulSoup(dom_html or "", "html.parser").get_text(" ")


def required_field_count(dom_html: str) -> int:
    soup = BeautifulSoup(dom_html or "", "html.parser")
    return len(soup.select("input[required], select[required], textarea[required]"))


def has_interstitial(dom_html: str) -> bool:
    soup = BeautifulSoup(dom_html or "", "html.parser")
    for el in soup.find_all(True):
        if (el.get("role") or "").lower() == "dialog":
            return True
        class_and_id = (" ".join(el.get("class") or []) + " " + (el.get("id") or "")).lower()
        if any(kw in class_and_id for kw in _INTERSTITIAL_KEYWORDS):
            return True
    return False


def has_no_interactive_elements(dom_html: str) -> bool:
    soup = BeautifulSoup(dom_html or "", "html.parser")
    return len(soup.select(_INTERACTIVE_SELECTOR)) == 0


_RETENTION_OFFER_PATTERNS = [
    re.compile(r"before\s+you\s+go", re.IGNORECASE),
    re.compile(r"special\s+offer", re.IGNORECASE),
    re.compile(r"wait[!,]", re.IGNORECASE),
    re.compile(r"we'?d\s+hate\s+to\s+see\s+you\s+go", re.IGNORECASE),
    re.compile(r"stay\s+with\s+us", re.IGNORECASE),
    re.compile(r"\d+%\s+off", re.IGNORECASE),
    re.compile(r"don'?t\s+leave", re.IGNORECASE),
    re.compile(r"one\s+more\s+chance", re.IGNORECASE),
]


def has_retention_offer(dom_html: str) -> bool:
    text = full_text(dom_html)
    return any(pattern.search(text) for pattern in _RETENTION_OFFER_PATTERNS)
