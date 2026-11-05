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

Two independent dimensions, each MEASURED separately from whether it's
CLEAN -- a real bug fixed here: friction_ratio can be null for two very
different reasons (never paired at extract-evidence time, vs. genuinely
paired and computed) and forced_interstitial_count can be a vacuous 0 for
two very different reasons (genuinely zero forced interstitials, vs. no
step captured usable DOM data to look for one in at all -- see
signals/path_deviation.py, which silently treats a null dom_html as "no
interstitial here"). Either "None"/zero used to be treated as "measured
and clean" unconditionally; now each dimension is skipped (not counted as
clean, not counted as firing) when it genuinely couldn't be measured, and
the whole assessment is not_assessable only if NEITHER dimension could be
measured at all -- the same "skip an unmeasurable dimension, don't fake a
clean reading" pattern attribute_agents/complexity.py already uses.

Three-tiered off the SAME kind of baseline distribution per measured
dimension: below median is clean, [median, p75) is "unsure", and
>=p75*restriction_p75_factor ("the configurable factor") is "fires";
[p75, p75*factor) also lands in "unsure" -- a confident recompute is
required to call it a firm "fires", not just clearing the raw p75 mark.
"""

from typing import Dict, List, Optional, Tuple

from attribute_agents.base import AttributeAgent, not_assessable_result, scale_severity
from journey.baselines import Baseline, BaselineStore

AGENT_VERSION = "restriction_code/1.0.0"


def _tier(value: float, threshold: Baseline, factor: float) -> Optional[str]:
    """None here means "clean" (measured, below median) -- callers only
    invoke this once the value is already known to be a real measurement,
    never a stand-in for "not measured" (see _ratio_dimension /
    _interstitial_dimension, which decide THAT separately)."""
    if value >= threshold.p75 * factor:
        return "fires"
    if value >= threshold.median:
        return "unsure"
    return None


def _has_any_usable_step(episode: Dict) -> bool:
    """False when no step in this episode ever had a masked DOM snapshot to
    look at -- the scenario where signals/path_deviation.py's forced-
    interstitial count is a vacuous 0 (nothing to detect one in) rather
    than a genuine "checked, found none". Checking dom_snapshot_masked_path
    directly (not just step.capture_error) matters because a v1-migrated
    episode has capture_error=None on every step (v1 had no partial-failure
    representation -- see journey/schema_migration.py) AND
    dom_snapshot_masked_path=None on every step (v1 never masked anything),
    so capture_error alone would wrongly call it measurable."""
    steps = episode.get("steps") or []
    return any(step.get("dom_snapshot_masked_path") for step in steps)


def _ratio_dimension(friction_ratio: Optional[float], threshold: Baseline, factor: float) -> Optional[Tuple[str, str]]:
    """Returns (tier_or_"clean", detail) or None if friction_ratio was
    never computed at all (not paired at extract-evidence time)."""
    if friction_ratio is None:
        return None
    tier = _tier(friction_ratio, threshold, factor) or "clean"
    return tier, f"friction_ratio={friction_ratio:.2f} ({tier})"


def _interstitial_dimension(
    forced_interstitials: List[Dict], threshold: Baseline, factor: float, episode: Dict
) -> Optional[Tuple[str, str]]:
    """Returns (tier_or_"clean", detail) or None if no step in this
    episode captured usable DOM data to count forced interstitials from --
    a count of 0 in that situation is not evidence of a clean flow."""
    if not _has_any_usable_step(episode):
        return None
    tier = _tier(float(len(forced_interstitials)), threshold, factor) or "clean"
    return tier, f"{len(forced_interstitials)} forced interstitial(s) ({tier})"


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

    ratio_dim = _ratio_dimension(friction_ratio, ratio_threshold, factor)
    interstitial_dim = _interstitial_dimension(forced_interstitials, interstitial_threshold, factor, episode)

    if ratio_dim is None and interstitial_dim is None:
        return not_assessable_result(
            "friction_ratio was never computed (this episode was not yet paired at extract-evidence time) "
            "and no step in this episode captured usable DOM data to count forced interstitials from -- "
            "restriction cannot be assessed from what's currently stored."
        )

    ratio_tier = ratio_dim[0] if ratio_dim and ratio_dim[0] != "clean" else None
    interstitial_tier = interstitial_dim[0] if interstitial_dim and interstitial_dim[0] != "clean" else None

    if ratio_tier is None and interstitial_tier is None:
        clean_details = [d[1] for d in (ratio_dim, interstitial_dim) if d is not None]
        skipped = []
        if ratio_dim is None:
            skipped.append("friction_ratio not available (not yet paired at extract-evidence time)")
        if interstitial_dim is None:
            skipped.append("forced_interstitial_count not assessable (no usable step DOM data)")
        reasoning = "; ".join(clean_details + skipped) + "."
        return {
            "verdict": "no", "severity": None, "confidence": 0.5 if skipped else 0.7,
            "evidence_pointers": [], "reasoning": reasoning,
        }

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
        if ratio_dim is not None and ratio_threshold.p75:
            ratios.append(friction_ratio / ratio_threshold.p75)
        if interstitial_dim is not None and interstitial_threshold.p75:
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
