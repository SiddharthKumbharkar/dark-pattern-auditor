"""restriction: did this episode require disproportionately more steps,
or force more non-skippable interstitials, than its paired episode?
Code agent, pure function over episode.evidence.friction_metrics,
episode.evidence.path_deviation, and group_evidence.paired_flow_comparison.

MUST return not_assessable when there is no paired episode: the whole
agent is gated on group_evidence.paired_flow_comparison existing for this
episode, not just the friction_ratio path -- "restriction" in this
framework's sense is inherently a COMPARATIVE judgement (is this flow
more restrictive than it needs to be, relative to its counterpart), so a
forced-interstitial count in isolation, with nothing to compare it
against, is exactly as unmeasurable as a null friction_ratio.

Two independent firing paths, each three-tiered off the SAME kind of
baseline distribution: below median is clean, [median, p75) is "unsure",
and >=p75*restriction_p75_factor ("the configurable factor") is "fires";
[p75, p75*factor) also lands in "unsure" -- a confident recompute is
required to call it a firm "fires", not just clearing the raw p75 mark.
"""

from typing import Dict, List, Optional

from attribute_agents.base import AttributeAgent, no_result, not_assessable_result, scale_severity
from journey.baselines import Baseline, BaselineStore

AGENT_VERSION = "restriction_code/1.0.0"


def _tier(value: Optional[float], threshold: Baseline, factor: float) -> Optional[str]:
    if value is None:
        return None
    if value >= threshold.p75 * factor:
        return "fires"
    if value >= threshold.median:
        return "unsure"
    return None


def assess(episode: Dict, group_evidence: Optional[Dict], baselines: BaselineStore) -> Dict:
    comparisons = (group_evidence or {}).get("paired_flow_comparison") or []
    episode_id = (episode.get("episode") or {}).get("episode_id")
    relevant = [c for c in comparisons if episode_id in (c["episode_a_id"], c["episode_b_id"])]

    if not relevant:
        # required_signals already gates the fully-empty group_evidence
        # case; this covers the narrower case where OTHER pairs exist in
        # the group but none involve this specific episode.
        return not_assessable_result(f"No paired_flow_comparison entry involves episode {episode_id!r} -- not paired.")

    friction_ratio = ((episode.get("evidence") or {}).get("friction_metrics") or {}).get("friction_ratio")
    path_deviation = (episode.get("evidence") or {}).get("path_deviation") or []
    forced_interstitials = [e for e in path_deviation if e.get("event_type") == "forced_interstitial"]

    ratio_threshold = baselines.get("restriction_friction_ratio_threshold")
    interstitial_threshold = baselines.get("restriction_forced_interstitial_count_threshold")
    factor = baselines.get("restriction_p75_factor").median

    ratio_tier = _tier(friction_ratio, ratio_threshold, factor)
    interstitial_tier = _tier(float(len(forced_interstitials)), interstitial_threshold, factor)

    if ratio_tier is None and interstitial_tier is None:
        return no_result(
            f"friction_ratio={friction_ratio} and forced_interstitial_count={len(forced_interstitials)} "
            f"are both below their restriction thresholds."
        )

    verdict = "fires" if "fires" in (ratio_tier, interstitial_tier) else "unsure"

    evidence_pointers: List[Dict] = []
    reasons = []
    if ratio_tier is not None:
        evidence_pointers.append({"step_id": None, "selector": None, "signal": "friction_metrics.friction_ratio"})
        reasons.append(f"friction_ratio={friction_ratio:.2f} ({ratio_tier})")
    if interstitial_tier is not None:
        evidence_pointers.extend(
            {"step_id": e["step_id"], "selector": None, "signal": "path_deviation.forced_interstitial"}
            for e in forced_interstitials
        )
        reasons.append(f"{len(forced_interstitials)} forced interstitial(s) ({interstitial_tier})")

    if verdict == "fires":
        ratios = []
        if friction_ratio is not None and ratio_threshold.p75:
            ratios.append(friction_ratio / ratio_threshold.p75)
        if interstitial_threshold.p75:
            ratios.append(len(forced_interstitials) / interstitial_threshold.p75)
        severity = scale_severity(max(ratios) if ratios else 1.0, 1.0)
    else:
        severity = None

    return {
        "verdict": verdict,
        "severity": severity,
        "confidence": 0.8 if verdict == "fires" else 0.5,
        "evidence_pointers": evidence_pointers,
        "reasoning": "; ".join(reasons) + ".",
    }


AGENT = AttributeAgent(
    agent_id="restriction_code_v1",
    attribute="restriction",
    agent_version=AGENT_VERSION,
    agent_type="code",
    required_signals=["group_evidence.paired_flow_comparison"],
    assess=assess,
)
