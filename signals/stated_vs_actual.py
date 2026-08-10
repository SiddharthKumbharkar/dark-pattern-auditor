"""Stated action vs. actual network activity (Layer 3). Pure measurement,
no LLM, no subjective judgement about WHETHER a request "really" performed
the claimed action -- only whether one fired, or a genuine client-side
route change happened, at all.

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

"route_changed": a genuinely client-side-only app (no backend at all --
e.g. a demo/mock site whose "cancel" is a React state update persisted to
sessionStorage, never a network call) can perform a completely real state
change with ZERO network activity. network_fired alone would misread
every such action as a dead no-op. route_changed (the step's URL differs
from the immediately preceding step's) is a second, independent way a
real state transition can show up; a claimed action counts as verified if
EITHER fired -- attribute_agents/deception.py only treats an action as
suspicious when NEITHER did. This still makes no claim about whether the
action was truthful beyond "something observably happened" -- a page that
fakes a route change with no real backend effect is outside what this
signal alone can catch, same limitation network_fired always had for a
backend that lies in its response.
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

        previous_step = steps[i - 1]
        previous_elements = computed_styles_by_step_id.get(previous_step["step_id"]) or []
        matched_text = next(
            (el.get("text") for el in previous_elements if el.get("selector") == action["selector"]), None
        )
        if not matched_text or not STATE_CHANGE_VERBS.search(matched_text):
            continue

        network_events = step.get("network_events") or []
        previous_url = previous_step.get("page_url_redacted")
        current_url = step.get("page_url_redacted")
        route_changed = bool(previous_url) and bool(current_url) and previous_url != current_url

        results.append(
            {
                "claimed_action": matched_text,
                "step_id": step["step_id"],
                "network_fired": len(network_events) > 0,
                "route_changed": route_changed,
                "request_ids": [e.get("request_id") for e in network_events if e.get("request_id")],
            }
        )

    return results
