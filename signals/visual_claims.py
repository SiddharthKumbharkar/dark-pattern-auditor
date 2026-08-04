"""Hallucination guard on screenshot-based reasoning (Layer 3, pure text
matching -- no I/O, no model calls).

Shared by two very different call sites that both need the SAME answer to
"does this reasoning text claim to have visually inspected a screenshot":
  - attribute_agents/base.py -- code agents never receive an image, so any
    hit here is always a bug in the agent (hard-fail), never a flag to set.
  - journey/mechanism_verdict_ingest.py -- Stage-2 LLM responses DO
    (sometimes) receive images, so a hit here just triggers the
    grounding check (an image-sourced evidence_pointer, or an explicit
    visual_claim_unverified: true) rather than an automatic rejection.

Kept as one small curated list rather than a general sentiment/vision
classifier: false negatives here are safe (the ingest-time check still
requires image-sourced pointers for genuinely visual attributes like
asymmetry/covertness independent of this heuristic), false positives are
just an extra grounding requirement, not a rejection -- so a short, high-
precision list is the right trade-off over broad recall.
"""

import re
from typing import Dict

_VISUAL_CLAIM_PATTERNS = [
    re.compile(r"\bscreenshot\w*\s+shows?\b", re.IGNORECASE),
    re.compile(r"\bthe\s+image\s+shows?\b", re.IGNORECASE),
    re.compile(r"\bvisually\b", re.IGNORECASE),
    re.compile(r"\bvisible\s+to\s+the\s+(eye|user)\b", re.IGNORECASE),
    re.compile(r"\b(clearly|barely)\s+legible\b", re.IGNORECASE),
    re.compile(r"\byou\s+can\s+see\b", re.IGNORECASE),
    re.compile(r"\bappears?\s+(lighter|darker|larger|smaller|faded|blended)\b", re.IGNORECASE),
    re.compile(r"\blooking\s+at\s+the\s+screenshot\b", re.IGNORECASE),
    re.compile(r"\bas\s+(shown|seen)\s+in\s+the\s+screenshot\b", re.IGNORECASE),
]

# The convention every image-grounded evidence_pointer's "signal" field
# must use so this module (and journey/mechanism_verdict_ingest.py) can
# tell an image-sourced pointer apart from a measured-signal one without
# guessing -- see prompts/attribute_prompt.v1.txt, which tells the model
# this exact prefix.
IMAGE_SOURCED_SIGNAL_PREFIX = "screenshot_visual_inspection"


def has_visual_claim(reasoning: str) -> bool:
    if not reasoning:
        return False
    return any(pattern.search(reasoning) for pattern in _VISUAL_CLAIM_PATTERNS)


def pointer_is_image_sourced(pointer: Dict) -> bool:
    signal = pointer.get("signal") or ""
    return signal.startswith(IMAGE_SOURCED_SIGNAL_PREFIX)
