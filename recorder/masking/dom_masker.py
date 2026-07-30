"""Redacts a captured DOM snapshot (Layer 1/masking).

Pure Python -- no Playwright, no file I/O -- given the raw DOM HTML string
(recorder.dom.extract_dom's output) and a small amount of form-field
metadata the caller already probed from the live page (recorder/masking/
browser_probe.py). Testable with plain HTML strings and dicts, no browser
needed.

Two redaction passes, ALLOWLIST CHECKED BEFORE DENYLIST as required:
  1. Form fields (input/textarea/select): type- and name/autocomplete-
     denylist-based, using recorder.redaction.should_redact -- unconditional
     for password/email/tel types, never checked against the allowlist
     (a form field being redacted has nothing to do with whether its
     current value happens to look like preserved copy).
  2. General text content: for every text node, the allowlist (price,
     urgency/social-proof phrasing, headings, buttons, timers, cookie
     banners, error messages -- see patterns.py) is checked FIRST; only if
     none of those match does PII detection (card/email/phone/address) run
     at all. This ordering is what makes an allowlisted node immune to
     redaction even if a PII-shaped substring coincidentally appears in it.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from bs4 import BeautifulSoup, NavigableString

from recorder.masking.patterns import (
    BUTTON_INPUT_TYPES,
    BUTTON_ROLES,
    BUTTON_TAGS,
    COOKIE_BANNER_ANCESTOR_KEYWORDS,
    ERROR_MESSAGE_ANCESTOR_KEYWORDS,
    HEADING_TAGS,
    TIMER_ANCESTOR_KEYWORDS,
    find_card_numbers,
    find_emails,
    find_phone_numbers,
    find_protected_spans,
    looks_like_address,
)
from recorder.masking.placeholders import (
    PLACEHOLDER_ADDRESS,
    PLACEHOLDER_CARD,
    PLACEHOLDER_EMAIL,
    PLACEHOLDER_PASSWORD,
    PLACEHOLDER_PHONE,
)
from recorder.redaction import should_redact

_FIELD_TYPE_PLACEHOLDERS = {
    "password": (PLACEHOLDER_PASSWORD, "password_field"),
    "email": (PLACEHOLDER_EMAIL, "email_field"),
    "tel": (PLACEHOLDER_PHONE, "tel_field"),
}


@dataclass
class DomMaskResult:
    masked_html: str
    redaction_kinds: List[str] = field(default_factory=list)
    # Bounding boxes already known from the form-field probe -- no further
    # live lookup needed to black these out on the screenshot.
    redacted_boxes: List[Dict] = field(default_factory=list)
    # CSS selectors for text-node redactions, which DO need a follow-up
    # live bounding-box lookup (see recorder/masking/masker.py).
    text_redaction_selectors: List[str] = field(default_factory=list)


_KIND_PRIORITY = {"card": 0, "email": 1, "phone": 2}


def _overlaps_any(start: int, end: int, spans: List[Tuple[int, int]]) -> bool:
    return any(s < end and start < e for s, e in spans)


def redact_text_span(text: str) -> Tuple[str, List[str]]:
    """Denylist pass for one span of text (a DOM text node here; also
    reused directly by recorder/browser.py for the v1 pipeline's
    visible_text_summary, which has no DOM structure of its own to walk --
    just a flat list of strings from the live page). ALLOWLIST CHECKED FIRST at the
    span level: a scarcity/price/urgency phrase's own span is protected
    even when the same text node also contains real PII elsewhere (e.g.
    "Only 2 left in stock! Contact support@example.com" must keep the
    scarcity phrase intact AND still redact the email -- protecting the
    whole node would leak the email; only protecting the matched span
    does not).

    All candidate spans are found against the ORIGINAL text first, then
    filtered/resolved, then applied in one right-to-left pass -- avoiding
    the offset bugs a sequential redact-then-rescan approach would have.
    """
    protected = list(find_protected_spans(text))

    candidates: List[Tuple[int, int, str, str]] = []
    for start, end in find_card_numbers(text):
        candidates.append((start, end, PLACEHOLDER_CARD, "card"))
    for start, end in find_emails(text):
        candidates.append((start, end, PLACEHOLDER_EMAIL, "email"))
    for start, end in find_phone_numbers(text):
        candidates.append((start, end, PLACEHOLDER_PHONE, "phone"))

    candidates = [c for c in candidates if not _overlaps_any(c[0], c[1], protected)]
    candidates.sort(key=lambda c: (c[0], _KIND_PRIORITY[c[3]]))

    accepted: List[Tuple[int, int, str, str]] = []
    for candidate in candidates:
        if not _overlaps_any(candidate[0], candidate[1], [(a[0], a[1]) for a in accepted]):
            accepted.append(candidate)

    result = text
    for start, end, placeholder, _ in sorted(accepted, key=lambda c: c[0], reverse=True):
        result = result[:start] + placeholder + result[end:]

    kinds = [c[3] for c in accepted]
    if not kinds and looks_like_address(result):
        result = PLACEHOLDER_ADDRESS
        kinds = ["address"]

    return result, kinds


def _css_selector(tag) -> Optional[str]:
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


def _ancestor_class_or_id_matches(tag, keywords: List[str]) -> bool:
    node = tag
    while node is not None and getattr(node, "name", None):
        class_attr = " ".join(node.get("class") or []).lower()
        id_attr = (node.get("id") or "").lower()
        if any(kw in class_attr or kw in id_attr for kw in keywords):
            return True
        node = node.parent
    return False


def _is_structurally_allowlisted(tag) -> bool:
    """Whole-node exemptions based on what the node IS (heading, button,
    timer, cookie banner, error message), as opposed to content-pattern
    exemptions (price/urgency/social-proof), which are handled at the
    span level inside redact_text_span instead -- a node's ROLE justifies
    skipping it entirely; a node merely CONTAINING allowlisted phrasing
    does not, because it might also contain real PII elsewhere in the
    same node (see redact_text_span's docstring)."""
    node = tag
    depth = 0
    while node is not None and getattr(node, "name", None) and depth < 6:
        name = node.name.lower()
        if name in HEADING_TAGS or name in BUTTON_TAGS:
            return True
        if (node.get("role") or "").lower() in BUTTON_ROLES:
            return True
        if name == "input" and (node.get("type") or "").lower() in BUTTON_INPUT_TYPES:
            return True
        node = node.parent
        depth += 1

    return (
        _ancestor_class_or_id_matches(tag, TIMER_ANCESTOR_KEYWORDS)
        or _ancestor_class_or_id_matches(tag, COOKIE_BANNER_ANCESTOR_KEYWORDS)
        or _ancestor_class_or_id_matches(tag, ERROR_MESSAGE_ANCESTOR_KEYWORDS)
    )


def _mask_form_fields(
    soup: BeautifulSoup, form_fields: List[Dict], field_denylist: Optional[List[str]]
) -> Tuple[List[str], List[Dict]]:
    redaction_kinds: List[str] = []
    redacted_boxes: List[Dict] = []

    for entry in form_fields:
        if not entry.get("has_value"):
            continue

        field_type = (entry.get("type") or "").lower()
        name = entry.get("name") or entry.get("id") or ""
        autocomplete = entry.get("autocomplete") or ""
        # Many real-world (esp. React-controlled) inputs carry no
        # name/id/autocomplete at all -- placeholder text ("Full name",
        # "PIN code") is often the only semantic signal available, so it's
        # checked against the same denylist as a second, independent path
        # to "this is a sensitive field".
        field_placeholder_text = entry.get("placeholder") or ""

        replacement_text, kind = _FIELD_TYPE_PLACEHOLDERS.get(field_type, (None, None))
        if replacement_text is None and (
            should_redact(name, field_type, autocomplete, field_denylist)
            or should_redact(field_placeholder_text, field_type, "", field_denylist)
        ):
            label = name or field_placeholder_text or "field"
            replacement_text = f"[REDACTED:{label}]"
            kind = "sensitive_field"
        if replacement_text is None:
            continue

        selector = entry.get("selector")
        element = soup.select_one(selector) if selector else None
        if element is not None:
            if element.name == "textarea":
                element.string = replacement_text
            else:
                element["value"] = replacement_text

        redaction_kinds.append(kind)
        box = entry.get("bounding_box")
        if box:
            redacted_boxes.append(box)

    return redaction_kinds, redacted_boxes


def _mask_text_nodes(soup: BeautifulSoup) -> Tuple[List[str], List[str]]:
    redaction_kinds: List[str] = []
    selectors: List[str] = []

    for node in list(soup.find_all(string=True)):
        if not isinstance(node, NavigableString) or not node.strip():
            continue
        parent = node.parent
        if parent is None or parent.name in ("script", "style"):
            continue
        if _is_structurally_allowlisted(parent):
            continue

        new_text, kinds = redact_text_span(str(node))
        if not kinds:
            continue

        node.replace_with(new_text)
        redaction_kinds.extend(kinds)
        selector = _css_selector(parent)
        if selector:
            selectors.append(selector)

    return redaction_kinds, sorted(set(selectors))


def mask_dom_html(
    dom_html: str,
    form_fields: Optional[List[Dict]] = None,
    field_denylist: Optional[List[str]] = None,
) -> DomMaskResult:
    """form_fields: [{selector, name, id, type, autocomplete, has_value,
    bounding_box}], from recorder/masking/browser_probe.py -- note it never
    carries the actual field VALUE, only whether one is present, so a raw
    secret is never even transmitted into this function, let alone
    persisted."""
    soup = BeautifulSoup(dom_html or "", "html.parser")

    field_kinds, redacted_boxes = _mask_form_fields(soup, form_fields or [], field_denylist)
    text_kinds, text_selectors = _mask_text_nodes(soup)

    return DomMaskResult(
        masked_html=str(soup),
        redaction_kinds=field_kinds + text_kinds,
        redacted_boxes=redacted_boxes,
        text_redaction_selectors=text_selectors,
    )
