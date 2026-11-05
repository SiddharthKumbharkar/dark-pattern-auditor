"""Forced interstitials, redirects, and dead-ends between a user's action
and the resulting captured state (Layer 3). Pure measurement over
already-loaded step/DOM data, no LLM, no subjective judgement.

Definitions (all structural, all reproducible from the stored episode):
  - forced_interstitial: this step's DOM shows a modal/dialog-shaped
    element (see signals.dom_text.has_interstitial) that the PREVIOUS
    step's DOM did not -- a newly-appeared blocking overlay.
  - redirect: this step's action.type is "navigate", meaning no captured
    click/submit/input/scroll trigger preceded it -- the page changed
    without a user-initiated trigger the recorder could attribute (a
    client/server redirect, or a browser back/forward/typed URL).
  - dead_end: this step's DOM has zero interactive elements.
"""

from typing import Dict, List, Optional

from signals.dom_text import has_interstitial, has_no_interactive_elements


def compute_path_deviation(steps: List[Dict], dom_htmls: List[Optional[str]]) -> List[Dict]:
    """dom_htmls must be the same length as steps, aligned by index."""
    events: List[Dict] = []
    previous_had_interstitial = False

    for i, step in enumerate(steps):
        dom_html = dom_htmls[i]
        current_has_interstitial = has_interstitial(dom_html) if dom_html else False
        is_dead_end = has_no_interactive_elements(dom_html) if dom_html else False
        action_type = (step.get("action") or {}).get("type")

        from_url = steps[i - 1].get("page_url_redacted", "") if i > 0 else ""
        to_url = step.get("page_url_redacted")

        if current_has_interstitial and not previous_had_interstitial:
            events.append(
                {"step_id": step["step_id"], "event_type": "forced_interstitial", "from_url": from_url, "to_url": to_url}
            )

        if action_type == "navigate" and i > 0:
            events.append({"step_id": step["step_id"], "event_type": "redirect", "from_url": from_url, "to_url": to_url})

        if is_dead_end:
            events.append({"step_id": step["step_id"], "event_type": "dead_end", "from_url": to_url or "", "to_url": None})

        previous_had_interstitial = current_has_interstitial

    return events
