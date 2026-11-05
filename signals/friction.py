"""Friction metrics -- pure measurement over a stored (masked) episode's
steps (Layer 3). No LLM, no subjective judgement: every count here is a
literal count of something structurally present, over data the caller
(journey/evidence_extractor.py) already loaded from disk.
"""

from typing import Dict, List, Optional

from signals.dom_text import (
    has_interstitial,
    has_no_interactive_elements,
    has_retention_offer,
    required_field_count,
)


def compute_friction_metrics(
    steps: List[Dict], dom_htmls: List[Optional[str]], paired_step_count: Optional[int]
) -> Dict:
    """dom_htmls must be the same length as steps, aligned by index
    (dom_htmls[i] is steps[i]'s masked DOM, or None if unavailable).

    form_fields_required is the MAX count of [required] fields found in
    any single step's DOM across the episode, not a sum across steps --
    the same form is typically captured across several consecutive steps
    (e.g. before/after typing into a field), so summing would measure
    "how many steps happened to show a form" rather than "how demanding
    was the most demanding form the episode encountered".
    """
    clicks = sum(1 for step in steps if (step.get("action") or {}).get("type") == "click")

    required_counts = [required_field_count(html) for html in dom_htmls if html]
    form_fields_required = max(required_counts) if required_counts else 0

    confirmation_interstitials = sum(1 for html in dom_htmls if html and has_interstitial(html))
    retention_offers_detected = sum(1 for html in dom_htmls if html and has_retention_offer(html))
    dead_ends = sum(1 for html in dom_htmls if html and has_no_interactive_elements(html))

    step_count = len(steps)
    friction_ratio = (step_count / paired_step_count) if paired_step_count else None

    return {
        "steps": step_count,
        "clicks": clicks,
        "form_fields_required": form_fields_required,
        "confirmation_interstitials": confirmation_interstitials,
        "retention_offers_detected": retention_offers_detected,
        "dead_ends": dead_ends,
        "friction_ratio": friction_ratio,
    }
