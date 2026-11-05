"""ui_region tagging (Layer 3, pure): assigns every interactive element
captured by recorder/evidence_probe.py a stable ui_region id, using only
structural cues already present in the masked DOM -- containing landmark
(<nav>/<section>/<form>/... or an ARIA landmark role), the nearest
governing heading, and keyword matches on the element's own selector/
text/role. See config/ui_regions.py for the vocabulary and rule tables
this module is driven by.

A second, narrower pass also tags DISCLOSURE elements -- non-interactive
text (a cost, term, or condition) the page has explicitly opted into
region tagging for via a data-disclosure attribute, e.g.
<p data-disclosure="cancellation-fee">...</p>. recorder/evidence_probe.py's
capture is interactive-elements-only by design (buttons/links/inputs), so
a material disclosure rendered as plain text was previously invisible to
every downstream evidence_pointer -- an LLM judge that correctly READ such
text in a screenshot had no real, taggable element to cite, and any
selector it invented for one was (correctly) rejected at ingest time by
journey/mechanism_verdict_ingest.py's grounding check. This is deliberately
opt-in (an explicit attribute the page author adds), not "tag every <p> on
the page" -- see compute_ui_regions()'s docstring.

Deterministic and episode/revisit-stable by construction: the same
(selector, surrounding DOM) always classifies the same way, no randomness,
no LLM call, no dependency on which agent later reads the tag.

"unclassified" is a legitimate, common outcome -- this module never forces
an element into a named region it doesn't structurally match (see
config/ui_regions.py's docstring). Every attribute agent and the
coordinator read the region assigned HERE off episode.evidence.ui_regions;
none of them classify on their own (attribute_agents/base.py enforces
that by construction -- it is the only place downstream that touches a
region id).
"""

from typing import Dict, List, Optional

from bs4 import BeautifulSoup

from config.ui_regions import LANDMARK_ROLES, LANDMARK_TAGS, REGION_KEYWORDS, UNCLASSIFIED_REGION
from signals.dom_text import css_selector

_HEADING_TAGS = ("h1", "h2", "h3", "h4")

# Opt-in marker a page author adds to a non-interactive element carrying
# evidentially important text (a cost/term/condition disclosure) so it
# gets a real, taggable selector even though recorder/evidence_probe.py's
# interactive-elements capture never sees it. The attribute's VALUE is
# free-form (a human-readable label, e.g. "cancellation-fee") and is
# never read by this module -- only its presence matters.
DISCLOSURE_ATTR = "data-disclosure"


def _ancestor_context_text(soup: BeautifulSoup, selector: str) -> str:
    """Best-effort: walk up from the element matching `selector` collecting
    landmark tag names, ARIA landmark roles, aria-label text, id/class
    tokens, and the nearest governing heading's text. Returns "" (not an
    exception) for anything bs4 can't resolve -- a selector that no longer
    matches (DOM drift between capture and this pass) degrades to
    keyword-only classification rather than failing the whole step.
    """
    try:
        element = soup.select_one(selector)
    except Exception:
        return ""
    if element is None:
        return ""

    parts: List[str] = []
    node = element
    depth = 0
    while node is not None and getattr(node, "name", None) and depth < 8:
        if node.name in LANDMARK_TAGS:
            parts.append(node.name)
        role = (node.get("role") or "").lower()
        if role in LANDMARK_ROLES:
            parts.append(role)
        for attr in ("aria-label", "id"):
            value = node.get(attr)
            if value:
                parts.append(str(value))
        classes = node.get("class") or []
        if classes:
            parts.append(" ".join(classes))
        heading = node.find(_HEADING_TAGS)
        if heading is not None:
            heading_text = heading.get_text(" ", strip=True)
            if heading_text:
                parts.append(heading_text)
        node = node.parent
        depth += 1

    return " ".join(parts).lower()


def classify_region(selector: Optional[str], text: str, role: str, ancestor_context: str) -> str:
    """Pure keyword match over everything known about one element -- its
    own selector/text/role plus whatever _ancestor_context_text found.
    First region in config.ui_regions.REGION_KEYWORDS whose keyword list
    hits wins; REGION_KEYWORDS' own ordering is what encodes "check the
    more specific region before the broader one it can sit inside"
    (e.g. retention_offer before cancellation_flow).
    """
    haystack = " ".join(filter(None, [selector or "", text or "", role or "", ancestor_context])).lower()
    for region, keywords in REGION_KEYWORDS.items():
        if any(keyword in haystack for keyword in keywords):
            return region
    return UNCLASSIFIED_REGION


def compute_ui_regions(steps: List[Dict], dom_htmls: List[Optional[str]], computed_styles: List[Optional[List[Dict]]]) -> List[Dict]:
    """One entry per (step, interactive element) captured by
    recorder/evidence_probe.py, PLUS one entry per (step, disclosure
    element) explicitly marked with DISCLOSURE_ATTR -- zipped positionally
    with `steps` the same way journey/evidence_extractor.py already zips
    dom_htmls/computed_styles for every other signal. A step with no DOM
    contributes nothing at all; a step with DOM but no computed_styles
    (capture_error on that one capture, or pre-instrumentation-era data)
    still gets scanned for disclosure elements, since that pass reads the
    DOM directly and doesn't depend on the interactive-elements probe
    having succeeded -- never a fabricated "unclassified" entry for an
    element that was never even seen, in either pass.

    Returns [{"step_id": int, "selector": str, "region": str}, ...],
    stored verbatim into episode.evidence.ui_regions by
    journey/evidence_extractor.py.
    """
    tags: List[Dict] = []
    for step, html, elements in zip(steps, dom_htmls, computed_styles):
        if not html:
            continue
        soup = BeautifulSoup(html, "html.parser")
        seen_selectors = set()

        for element in elements or []:
            selector = element.get("selector")
            if not selector:
                continue
            seen_selectors.add(selector)
            ancestor_context = _ancestor_context_text(soup, selector)
            region = classify_region(selector, element.get("text") or "", element.get("role") or "", ancestor_context)
            tags.append({"step_id": step["step_id"], "selector": selector, "region": region})

        for disclosure_el in soup.select(f"[{DISCLOSURE_ATTR}]"):
            selector = css_selector(disclosure_el)
            if not selector or selector in seen_selectors:
                continue
            text = disclosure_el.get_text(" ", strip=True)
            if not text:
                continue
            seen_selectors.add(selector)
            ancestor_context = _ancestor_context_text(soup, selector)
            region = classify_region(selector, text, "", ancestor_context)
            # "text" is carried on the tag itself (unlike an interactive
            # element's tag, which omits it) so a downstream payload can
            # show a human/LLM judge a real (selector, text) pair to cite
            # -- without this, the selector existing in region_map alone
            # wouldn't help: nothing tells the model what string to write.
            # See llm/payload_builder.py's _disclosure_elements().
            tags.append({"step_id": step["step_id"], "selector": selector, "region": region, "text": text})
    return tags
