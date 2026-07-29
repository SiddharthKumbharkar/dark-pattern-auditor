"""deception: does a claimed state-change action (unsubscribe/cancel/
reject/etc.) fire no network request, does a claim show an implausible
persistence pattern across revisits, or does a countdown timer reset
instead of counting down? Code agent, pure function over
episode.evidence.stated_vs_actual and (when available)
group_evidence.claim_persistence / timer_reset_detection.

Fires ONLY on these three VERIFIED, structural contradictions -- never on
how aggressive or manipulative a claim's wording sounds. Every check here
reads a boolean/enum field (network_fired, claim_persistence.verdict,
reset_detected) that was already computed by measurement in an earlier
stage (signals/stated_vs_actual.py, signals/claim_persistence.py,
signals/timer_reset.py); this module never looks at claim_text or any
other free-text field, so there is no code path by which "the claim looks
aggressive" could influence the verdict -- if the only evidence available
is wording, none of the three checks below produce a finding and the
result is "no" (or "unsure"/"not_assessable", never "fires").

No single required_signals path covers assessability cleanly (an empty
stated_vs_actual list is a legitimate "nothing to check" result, not
missing data -- see the module docstring in signals/stated_vs_actual.py),
so required_signals is deliberately empty and not_assessable is decided
by assess() itself when NONE of the three data sources have anything at all.
"""

from typing import Dict, List, Optional

from attribute_agents.base import AttributeAgent, no_result, not_assessable_result, scale_severity
from journey.baselines import BaselineStore

AGENT_VERSION = "deception_code/1.0.0"


def assess(episode: Dict, group_evidence: Optional[Dict], baselines: BaselineStore) -> Dict:
    stated_vs_actual = (episode.get("evidence") or {}).get("stated_vs_actual") or []
    claim_persistence = (group_evidence or {}).get("claim_persistence") or []
    timer_resets = (group_evidence or {}).get("timer_reset_detection") or []
    min_evidence = baselines.get("deception_min_evidence_count")

    if not stated_vs_actual and not claim_persistence and not timer_resets:
        return not_assessable_result(
            "No state-change action was attempted and no group-level claim/timer data is available."
        )

    evidence_pointers: List[Dict] = []
    reasons: List[str] = []

    no_network = [s for s in stated_vs_actual if not s["network_fired"]]
    if no_network:
        evidence_pointers.extend(
            {"step_id": s["step_id"], "selector": None, "signal": "stated_vs_actual.network_fired"} for s in no_network
        )
        reasons.append(
            f"{len(no_network)} claimed action(s) (e.g. {no_network[0]['claimed_action']!r}) fired no network request"
        )

    implausible = [c for c in claim_persistence if c["verdict"] == "implausible"]
    if implausible:
        evidence_pointers.extend(
            {"step_id": None, "selector": c["selector"], "signal": "claim_persistence.verdict"} for c in implausible
        )
        reasons.append(f"{len(implausible)} claim(s) showed an implausible persistence pattern across revisits")

    resets = [t for t in timer_resets if t["reset_detected"]]
    if resets:
        evidence_pointers.extend(
            {"step_id": None, "selector": t["selector"], "signal": "timer_reset_detection.reset_detected"} for t in resets
        )
        reasons.append(f"{len(resets)} countdown timer(s) reset instead of counting down")

    total_findings = len(no_network) + len(implausible) + len(resets)

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
        f"Checked {len(stated_vs_actual)} claimed action(s), {len(claim_persistence)} persisted claim(s), "
        f"{len(timer_resets)} timer comparison(s); found no mismatch."
    )


AGENT = AttributeAgent(
    agent_id="deception_code_v1",
    attribute="deception",
    agent_version=AGENT_VERSION,
    agent_type="code",
    required_signals=[],
    assess=assess,
)
