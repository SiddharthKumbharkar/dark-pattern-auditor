"""Stated action vs. actual network activity (Layer 3). Pure measurement,
no LLM, no subjective judgement about WHETHER a request "really" performed
the claimed action -- only whether one fired at all.

"Claimed action" label: a click step's own `action` has no text field in
the v2 schema (only type/selector/bounding_box/input_redacted), so the
label is recovered by looking up the click's selector in the PRECEDING
step's computed-styles element list -- that's the page state the user was
looking at when they made the click that produced THIS step (this
step's own computed_styles reflect the page AFTER the click, which may
have already navigated away). Only covers the same interactive-element
selector set recorder/evidence_probe.py captures (button/a/role=button/
input[type=submit|button|checkbox|radio]) -- a click on some other
element type has no recoverable label and is skipped, not guessed.

"network_fired within N ms": approximated by "this step's own
network_events is non-empty" -- network_events already means "everything
that fired since the previous step" (see recorder/network_capture.py),
so N is whatever wall-clock gap actually elapsed between steps, not a
fixed constant; that gap is itself available per-step via
signals/complexity.py's time_on_step if a caller wants to filter on it.
"""

import re
from typing import Dict, List

STATE_CHANGE_VERBS = re.compile(r"\b(unsubscribe|cancel|reject|opt[\s-]?out|delete|decline|deny)\b", re.IGNORECASE)


def find_stated_vs_actual(steps: List[Dict], computed_styles_by_step_id: Dict[int, List[Dict]]) -> List[Dict]:
    results: List[Dict] = []

    for i, step in enumerate(steps):
        action = step.get("action") or {}
        if action.get("type") != "click" or not action.get("selector") or i == 0:
            continue

        previous_step_id = steps[i - 1]["step_id"]
        previous_elements = computed_styles_by_step_id.get(previous_step_id) or []
        matched_text = next(
            (el.get("text") for el in previous_elements if el.get("selector") == action["selector"]), None
        )
        if not matched_text or not STATE_CHANGE_VERBS.search(matched_text):
            continue

        network_events = step.get("network_events") or []
        results.append(
            {
                "claimed_action": matched_text,
                "step_id": step["step_id"],
                "network_fired": len(network_events) > 0,
                "request_ids": [e.get("request_id") for e in network_events if e.get("request_id")],
            }
        )

    return results
