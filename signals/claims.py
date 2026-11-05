"""Scarcity/urgency/social-proof claim extraction (Layer 3). Typed regex
over already-extracted text candidates; no LLM, no subjective judgement.

Not using spaCy NER: this environment's Python is a protected
(Homebrew-managed) system interpreter, and spaCy isn't installed --
installing it would require overriding that protection
(--break-system-packages, which pip explicitly warns can break the
install) plus a separate language-model download
(`python -m spacy download en_core_web_sm`), neither of which is
something to do unilaterally. Every claim type this module is asked to
extract (stock counts, countdown timers, viewer counts, "ends in", "last
chance") is a highly templated phrase fully covered by regex alone, so
nothing here is degraded by the absence -- but note spaCy NER is itself
a statistical model making probabilistic predictions, which sits
awkwardly next to "no heuristic judgement, only measurement" anyway;
regex-only keeps every extraction exactly reproducible from the pattern
that matched, with no model version to pin or drift.
"""

import re
from typing import Dict, List

from signals.urgency import SOCIAL_PROOF_PATTERNS, URGENCY_PHRASES

_STOCK_COUNT = re.compile(r"\bonly\s+(\d+)\s+(?:items?\s+)?left\b", re.IGNORECASE)
_STOCK_COUNT_BARE = re.compile(r"\b(\d+)\s+(?:items?\s+)?left\b", re.IGNORECASE)
_COUNTDOWN_HMS = re.compile(r"\b(\d{1,2}):(\d{2}):(\d{2})\b")
_COUNTDOWN_MS = re.compile(r"\b(\d{1,2}):(\d{2})\b")

# Disqualifies an HH:MM(:SS)-shaped match from being read as a countdown
# timer -- found via a real false positive testing against nytimes.com's
# cookie-consent vendor-disclosure text, which matched both an article
# byline ("Aug. 11, 2026, 11:09 a.m. ET") and an unrelated sentence
# mentioning a time of day ("...after 6:30 p.m. to users...") as
# "countdown_timer" claims. Both are fully explained by carrying an am/pm
# marker or a calendar date/year in the same text -- a countdown counts
# down TO a fixed point, it doesn't also state a time of day or a date.
# Deliberately NOT also length-gated: an earlier version of this guard
# additionally rejected any long text node, but a real (if unusually
# worded) countdown/stock/viewer-count combination can legitimately share
# one longer sentence (see tests/test_evidence_extractor_e2e.py's fixture,
# "Only 2 left in stock! Ends in 00:05:00. 42 people are viewing this.")
# -- length alone was never actually needed to explain either observed
# false positive, so it's not part of this check; each check here must
# stay directly motivated by an observed false positive, not speculative.
_WALL_CLOCK_MARKER = re.compile(r"\b(a\.?m\.?|p\.?m\.?)\b", re.IGNORECASE)
_MONTH_NAME = (
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
    r"aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
)
_DATE_CONTEXT = re.compile(rf"\b(?:{_MONTH_NAME})\b|\b(?:19|20)\d{{2}}\b", re.IGNORECASE)

_ENDS_IN = re.compile(r"\bends?\s+in\s+(\d+)\s*(hours?|hrs?|minutes?|mins?|days?)\b", re.IGNORECASE)
_VIEWER_COUNT = re.compile(r"\b(\d+)\s+(?:other\s+)?(?:people\s+)?(?:are\s+)?(?:viewing|looking\s+at)\s+this\b", re.IGNORECASE)
_PURCHASE_COUNT = re.compile(r"\b(\d+)\s+people\s+bought\b", re.IGNORECASE)
_LAST_CHANCE = re.compile(r"\blast\s+chance\b", re.IGNORECASE)

_UNIT_TO_SECONDS = {
    "hour": 3600, "hours": 3600, "hr": 3600, "hrs": 3600,
    "minute": 60, "minutes": 60, "min": 60, "mins": 60,
    "day": 86400, "days": 86400,
}


def _looks_like_countdown_display(text: str) -> bool:
    """True unless `text` shows a positive sign of being a plain wall-clock
    timestamp/date rather than a rendered countdown-timer widget -- see
    the module-level comment above _WALL_CLOCK_MARKER for the real false
    positives this exists to reject. Two independent, narrow checks
    (am/pm, calendar date) rather than one broad heuristic, so each stays
    easy to reason about and each was directly motivated by an observed
    false positive, not speculative."""
    if _WALL_CLOCK_MARKER.search(text):
        return False
    if _DATE_CONTEXT.search(text):
        return False
    return True


def _extract_typed_claims(text: str) -> List[Dict]:
    """Returns claim dicts (without step_id/selector, added by the
    caller) for a single text candidate. A given text can produce more
    than one claim (e.g. a countdown AND a deadline phrase in one line)."""
    claims: List[Dict] = []

    match = _STOCK_COUNT.search(text) or _STOCK_COUNT_BARE.search(text)
    if match:
        claims.append({"claim_text": text, "normalized_value": int(match.group(1)), "claim_type": "stock_count"})

    if _looks_like_countdown_display(text):
        hms = _COUNTDOWN_HMS.search(text)
        if hms:
            h, m, s = (int(x) for x in hms.groups())
            claims.append({"claim_text": text, "normalized_value": h * 3600 + m * 60 + s, "claim_type": "countdown_timer"})
        else:
            ms = _COUNTDOWN_MS.search(text)
            if ms:
                m, s = (int(x) for x in ms.groups())
                claims.append({"claim_text": text, "normalized_value": m * 60 + s, "claim_type": "countdown_timer"})

    deadline = _ENDS_IN.search(text)
    if deadline:
        quantity, unit = int(deadline.group(1)), deadline.group(2).lower()
        seconds = quantity * _UNIT_TO_SECONDS.get(unit, 0)
        claims.append({"claim_text": text, "normalized_value": seconds or None, "claim_type": "deadline_phrase"})

    viewers = _VIEWER_COUNT.search(text)
    if viewers:
        claims.append({"claim_text": text, "normalized_value": int(viewers.group(1)), "claim_type": "viewer_count"})

    purchases = _PURCHASE_COUNT.search(text)
    if purchases:
        claims.append({"claim_text": text, "normalized_value": int(purchases.group(1)), "claim_type": "purchase_count"})

    if _LAST_CHANCE.search(text):
        claims.append({"claim_text": text, "normalized_value": None, "claim_type": "deadline_phrase"})

    if not claims:
        if any(p.search(text) for p in SOCIAL_PROOF_PATTERNS):
            claims.append({"claim_text": text, "normalized_value": None, "claim_type": "social_proof"})
        elif any(p.search(text) for p in URGENCY_PHRASES):
            claims.append({"claim_text": text, "normalized_value": None, "claim_type": "urgency_phrase"})

    return claims


def extract_claims(step_id: int, text_candidates: List[Dict]) -> List[Dict]:
    """text_candidates: [{"text": str, "selector": Optional[str]}, ...],
    e.g. from signals.dom_text.extract_text_candidates()."""
    results: List[Dict] = []
    seen = set()
    for entry in text_candidates:
        text = (entry.get("text") or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        for claim in _extract_typed_claims(text):
            claim["step_id"] = step_id
            claim["selector"] = entry.get("selector")
            results.append(claim)
    return results
