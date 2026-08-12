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
element type has no recoverable label and is skipped, not guessed. Label
text prefers innerText/value, falling back to aria-label when that's
empty (an icon-only close "x" button typically has no innerText at all,
but a real one still usually carries aria-label="Close" or similar) --
still nothing invented when BOTH are empty; that click is simply skipped,
same as before aria-label was captured.

Two, independent claim shapes get matched here, each checked against the
SAME network_fired/route_changed measurement but with OPPOSITE polarity,
because they make opposite implicit promises:
  - claim_kind="state_change" (STATE_CHANGE_VERBS: unsubscribe/cancel/
    reject/opt-out/delete/decline/deny): claims something REAL happens.
    Verified by network_fired OR route_changed firing -- see below.
  - claim_kind="dismiss" (DISMISS_LABELS: close/dismiss/skip/×/etc.):
    claims NOTHING beyond going away happens. A close control that
    triggers real navigation or a network request did something other
    than what it claimed -- attribute_agents/deception.py flags THAT
    combination, the mirror image of the state_change check.
DISMISS_LABELS is matched against the FULL normalized label
(re.fullmatch), not searched as a substring, so a longer label that
merely CONTAINS the word "close" (e.g. "Close your account") is never
swept into the dismiss check just because of that one word -- it isn't a
dismiss claim (the whole label isn't just "close"), and it isn't a
state_change claim either ("close" isn't one of STATE_CHANGE_VERBS, which
covers unsubscribe/cancel/reject/opt-out/delete/decline/deny but
deliberately not "close" itself, to avoid exactly this collision with the
plain "Close" dismiss button). That specific phrasing is simply outside
what either check covers today, not silently misclassified as either.

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
from typing import Dict, List, Optional

STATE_CHANGE_VERBS = re.compile(r"\b(unsubscribe|cancel|reject|opt[\s-]?out|delete|decline|deny)\b", re.IGNORECASE)

# Matched against the FULL normalized label (re.fullmatch), not searched as
# a substring -- see module docstring for why "close" inside a longer label
# must NOT match here. Covers the common icon glyphs a close "x" renders as
# text (×/✕/✖/x) alongside the usual words/short phrases.
DISMISS_LABELS = re.compile(r"(x|×|✕|✖|close|dismiss|skip|no,? thanks?|not now|maybe later|later|got it)", re.IGNORECASE)


def _claim_kind(label: str) -> Optional[str]:
    if STATE_CHANGE_VERBS.search(label):
        return "state_change"
    if DISMISS_LABELS.fullmatch(label.strip()):
        return "dismiss"
    return None


def find_stated_vs_actual(steps: List[Dict], computed_styles_by_step_id: Dict[int, List[Dict]]) -> List[Dict]:
    results: List[Dict] = []

    for i, step in enumerate(steps):
        action = step.get("action") or {}
        if action.get("type") != "click" or not action.get("selector") or i == 0:
            continue

        previous_step = steps[i - 1]
        previous_elements = computed_styles_by_step_id.get(previous_step["step_id"]) or []
        matched_element = next(
            (el for el in previous_elements if el.get("selector") == action["selector"]), None
        )
        if matched_element is None:
            continue
        label = (matched_element.get("text") or matched_element.get("aria_label") or "").strip()
        if not label:
            continue
        claim_kind = _claim_kind(label)
        if claim_kind is None:
            continue

        network_events = step.get("network_events") or []
        previous_url = previous_step.get("page_url_redacted")
        current_url = step.get("page_url_redacted")
        route_changed = bool(previous_url) and bool(current_url) and previous_url != current_url

        results.append(
            {
                "claimed_action": label,
                "claim_kind": claim_kind,
                "step_id": step["step_id"],
                "network_fired": len(network_events) > 0,
                "route_changed": route_changed,
                "request_ids": [e.get("request_id") for e in network_events if e.get("request_id")],
            }
        )

    return results
