"""PII detection (denylist) and preserved-category detection (allowlist).

Reuses this repo's existing signal-extraction patterns (signals/price.py,
signals/urgency.py) as the allowlist source where they already exist,
rather than maintaining a second, divergent copy of "what counts as
price/urgency/social-proof copy" -- see dom_masker.py's
allowlist-BEFORE-denylist ordering, which is what this module supports.
"""

import re
from typing import Iterator, Tuple

from signals.price import PRICE_PATTERNS
from signals.urgency import SOCIAL_PROOF_PATTERNS, TIMER_KEYWORDS, URGENCY_PHRASES

# -- denylist: PII content patterns --------------------------------------

EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# Deliberately conservative (fewer false positives on ordinary product/
# order numbers, quantities, etc.) over exhaustive international phone
# format coverage -- see _looks_like_phone's digit-count floor below.
PHONE_CANDIDATE_PATTERN = re.compile(
    r"(?<!\d)(?:\+?\d{1,3}[-.\s]?)?(?:\(\d{2,4}\)[-.\s]?)?\d{3,4}[-.\s]?\d{3,4}[-.\s]?\d{0,4}(?!\d)"
)

CARD_CANDIDATE_PATTERN = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")

ADDRESS_KEYWORDS = [
    "street", "st.", "avenue", "ave.", "road", "rd.", "lane", "ln.",
    "drive", "dr.", "boulevard", "blvd", "apt", "apartment", "suite",
    "floor", "block", "sector", "colony", "nagar", "marg",
    "pincode", "pin code", "zip code", "postal code",
]
_ADDRESS_KEYWORD_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in ADDRESS_KEYWORDS) + r")\b", re.IGNORECASE
)


def _luhn_valid(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def find_card_numbers(text: str) -> Iterator[Tuple[int, int]]:
    """Yields (start, end) spans of Luhn-valid 13-19 digit card numbers
    (spaces/hyphens inside the span are tolerated, e.g. "4111 1111 1111 1111")."""
    for match in CARD_CANDIDATE_PATTERN.finditer(text):
        digits = re.sub(r"[ -]", "", match.group())
        if 13 <= len(digits) <= 19 and _luhn_valid(digits):
            yield match.start(), match.end()


def find_phone_numbers(text: str) -> Iterator[Tuple[int, int]]:
    for match in PHONE_CANDIDATE_PATTERN.finditer(text):
        start, end = match.start(), match.end()
        # The pattern's optional leading "country code" group can end up
        # swallowing what's really the first digit group, which pushes an
        # optional separator at the end onto trailing whitespace instead
        # of a digit -- trim that back defensively rather than trying to
        # make the regex itself provably greedy-safe.
        while end > start and text[end - 1].isspace():
            end -= 1
        digit_count = sum(c.isdigit() for c in text[start:end])
        if digit_count >= 8:  # high enough to exclude quantities/order counters
            yield start, end


def find_emails(text: str) -> Iterator[Tuple[int, int]]:
    for match in EMAIL_PATTERN.finditer(text):
        yield match.start(), match.end()


def looks_like_address(text: str) -> bool:
    """Heuristic, not a parser: an address keyword (street/road/apartment/
    pincode/etc.) plus at least one digit (a house/street/PIN number)
    somewhere in the same text. Disclosed scope: will miss addresses with
    no keyword, and can over-flag unrelated copy that happens to combine
    a keyword with a digit (e.g. "Block 5 restock coming soon") -- in
    the masking-safety tradeoff this tool makes throughout, an
    occasional over-redaction is preferred to an under-redaction."""
    return bool(_ADDRESS_KEYWORD_PATTERN.search(text)) and any(c.isdigit() for c in text)


# -- allowlist: preserved-category detection -----------------------------


def matches_price_pattern(text: str) -> bool:
    return any(p.search(text) for p in PRICE_PATTERNS)


def matches_urgency_or_social_proof(text: str) -> bool:
    return any(p.search(text) for p in URGENCY_PHRASES) or any(p.search(text) for p in SOCIAL_PROOF_PATTERNS)


def find_protected_spans(text: str) -> Iterator[Tuple[int, int]]:
    """Spans matched by a CONTENT allowlist category (price, urgency,
    social-proof phrasing). Used to shield those exact spans from PII
    detection even within a text node that ALSO contains real PII
    elsewhere -- e.g. "Only 2 left in stock! Contact us at
    support@example.com" must preserve the scarcity phrase AND still
    redact the email, not treat the whole node as exempt just because
    part of it matched an allowlist pattern. See dom_masker._redact_text.
    """
    for pattern in (*PRICE_PATTERNS, *URGENCY_PHRASES, *SOCIAL_PROOF_PATTERNS):
        for match in pattern.finditer(text):
            yield match.start(), match.end()


HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
BUTTON_TAGS = {"button"}
BUTTON_ROLES = {"button"}
BUTTON_INPUT_TYPES = {"submit", "button", "reset"}

# Ancestor class/id keyword hints -> allowlist category. A node whose OWN
# class/id, or any ancestor's, contains one of these (case-insensitive)
# is treated as belonging to that preserved category regardless of what
# its text looks like.
TIMER_ANCESTOR_KEYWORDS = TIMER_KEYWORDS
COOKIE_BANNER_ANCESTOR_KEYWORDS = ["cookie", "consent", "gdpr"]
ERROR_MESSAGE_ANCESTOR_KEYWORDS = ["error", "alert", "invalid", "warning"]
