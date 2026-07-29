"""Typed placeholders the masker substitutes for redacted content.

Never blank redacted content -- a stable, typed placeholder lets
downstream signal extraction still see that a field existed and roughly
what kind it was (e.g. "[EMAIL]" vs "[CARD]" vs bare deletion).
"""

from collections import Counter
from typing import Dict, List

from recorder.redaction import PLACEHOLDER_TOKEN

PLACEHOLDER_EMAIL = "[EMAIL]"
PLACEHOLDER_PHONE = "[PHONE]"
PLACEHOLDER_CARD = "[CARD]"
PLACEHOLDER_ADDRESS = "[ADDRESS]"
PLACEHOLDER_PASSWORD = "[PASSWORD]"

__all__ = [
    "PLACEHOLDER_EMAIL",
    "PLACEHOLDER_PHONE",
    "PLACEHOLDER_CARD",
    "PLACEHOLDER_ADDRESS",
    "PLACEHOLDER_PASSWORD",
    "PLACEHOLDER_TOKEN",
    "tally_redactions",
]


def tally_redactions(step_id: int, kinds: List[str]) -> List[Dict]:
    """Collapses a flat list of redaction "kind" strings for one step into
    the {step_id, kind, count} shape episode.privacy.redactions_applied
    uses, sorted for stable output."""
    counts = Counter(kinds)
    return [
        {"step_id": step_id, "kind": kind, "count": count}
        for kind, count in sorted(counts.items())
    ]
