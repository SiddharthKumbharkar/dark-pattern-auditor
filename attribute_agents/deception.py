"""deception: does a claimed state-change action (unsubscribe/cancel/
reject/etc.) produce NEITHER a network request NOR a client-side route
change, or does a (non-timer) claim show an implausible persistence
pattern across revisits? Code agent, pure function over
episode.evidence.stated_vs_actual and (when available)
group_evidence.claim_persistence.

A claimed action needs only ONE of network_fired / route_changed to count
as verified -- a genuinely client-side-only app (no backend, e.g. a mock
demo whose "cancel" is a React state update with no network call ever)
can perform a completely real state change with zero network activity;
requiring a network call there would flag every honest action in that
app as deceptive. See signals/stated_vs_actual.py's module docstring for
the full reasoning and its limits.

Countdown/urgency timers are DELIBERATELY excluded from both evidence
channels this module reads, by policy decision (not a detection gap):
group_evidence.timer_reset_detection is never read at all, and any
claim_persistence entry with claim_type=="countdown_timer" is filtered
out before this module ever sees it. A timer that resets instead of
counting down, or stays frozen too long, is a genuinely measured fact --
but management decided this framework should never auto-fire or
auto-conclude "fake" from it, only detect-and-flag it for a human to
judge (see journey/episode_output_builder.py's overall.urgency_claims /
human_review_recommended, which is unaffected by this file and still
does exactly that). An earlier version of this file DID auto-fire on
group_evidence.timer_reset_detection's reset_detected flag -- removed
here, not merely never-added; see git history if reconstructing why.

Fires ONLY on these two VERIFIED, structural contradictions -- never on
how aggressive or manipulative a claim's wording sounds. Every check here
reads a boolean/enum field (network_fired, claim_persistence.verdict)
that was already computed by measurement in an earlier stage
(signals/stated_vs_actual.py, signals/claim_persistence.py); this module
never looks at claim_text or any other free-text field, so there is no
code path by which "the claim looks aggressive" could influence the
verdict -- if the only evidence available is wording, neither check below
produces a finding and the result is "no" (or "unsure"/"not_assessable",
never "fires").

No single required_signals path covers assessability cleanly (an empty
stated_vs_actual list is a legitimate "nothing to check" result, not
missing data -- see the module docstring in signals/stated_vs_actual.py),
so required_signals is deliberately empty and not_assessable is decided
by assess() itself when NEITHER data source has anything at all.
"""

from typing import Dict, List, Optional

from attribute_agents.base import AttributeAgent, no_result, not_assessable_result, scale_severity
from journey.baselines import BaselineStore

AGENT_VERSION = "deception_code/1.0.0"


def assess(episode: Dict, group_evidence: Optional[Dict], baselines: BaselineStore) -> Dict:
    stated_vs_actual = (episode.get("evidence") or {}).get("stated_vs_actual") or []
    # Countdown/urgency timers are detect-and-flag-for-human-review only --
    # never a source of an auto-fired or auto-concluded verdict here, by
    # policy (see module docstring). group_evidence.timer_reset_detection
    # is never read; a countdown_timer claim's own claim_persistence entry
    # is filtered out before anything below ever sees it.
    claim_persistence = [
        c for c in (group_evidence or {}).get("claim_persistence") or [] if c["claim_type"] != "countdown_timer"
    ]
    min_evidence = baselines.get("deception_min_evidence_count")

    if not stated_vs_actual and not claim_persistence:
        return not_assessable_result(
            "No state-change action was attempted and no non-timer group-level claim data is available."
        )

    evidence_pointers: List[Dict] = []
    reasons: List[str] = []

    no_state_change = [s for s in stated_vs_actual if not s["network_fired"] and not s.get("route_changed")]
    if no_state_change:
        evidence_pointers.extend(
            {"step_id": s["step_id"], "selector": None, "signal": "stated_vs_actual.network_fired"}
            for s in no_state_change
        )
        reasons.append(
            f"{len(no_state_change)} claimed action(s) (e.g. {no_state_change[0]['claimed_action']!r}) fired no "
            f"network request and produced no client-side route change"
        )

    implausible = [c for c in claim_persistence if c["verdict"] == "implausible"]
    if implausible:
        evidence_pointers.extend(
            {"step_id": None, "selector": c["selector"], "signal": "claim_persistence.verdict"} for c in implausible
        )
        reasons.append(f"{len(implausible)} claim(s) showed an implausible persistence pattern across revisits")

    total_findings = len(no_state_change) + len(implausible)

    if total_findings >= min_evidence.median:
        severity = scale_severity(total_findings, min_evidence.median)
        return {
            "verdict": "fires",
            "severity": severity,
            "confidence": 0.7,
            "evidence_pointers": evidence_pointers,
            "reasoning": "; ".join(reasons) + ".",
        }

    # No verified contradiction -- but claim_persistence entries stuck at
    # "insufficient_data" (not enough revisits/elapsed time yet, see
    # signals/claim_persistence.py) mean we genuinely don't know either
    # way for THOSE claims, which is weaker than a clean "no" but still
    # nowhere near a verified finding.
    undetermined = [c for c in claim_persistence if c["verdict"] == "insufficient_data"]
    if undetermined:
        pointers = [
            {"step_id": None, "selector": c["selector"], "signal": "claim_persistence.verdict"} for c in undetermined
        ]
        return {
            "verdict": "unsure",
            "severity": None,
            "confidence": 0.3,
            "evidence_pointers": pointers,
            "reasoning": (
                f"{len(undetermined)} claim(s) have not yet accumulated enough revisits/elapsed time for a "
                f"persistence verdict; no other contradiction was found."
            ),
        }

    return no_result(
        f"Checked {len(stated_vs_actual)} claimed action(s), {len(claim_persistence)} non-timer persisted "
        f"claim(s); found no mismatch."
    )


AGENT = AttributeAgent(
    agent_id="deception_code_v1",
    attribute="deception",
    agent_version=AGENT_VERSION,
    agent_type="code",
    required_signals=[],
    assess=assess,
)
