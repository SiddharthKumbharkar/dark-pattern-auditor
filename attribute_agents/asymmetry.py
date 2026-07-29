"""asymmetry: does an opposing choice pair (accept/reject, keep/cancel,
yes/no, subscribe/decline) show a strong visual imbalance -- on contrast,
area, or vertical position? Code agent, pure function over
episode.evidence.visual_asymmetry (signals/visual_asymmetry.py).

Three-tier verdict per dimension, using the SAME baseline distribution's
median/p75 rather than a single cutoff: a value in [median, p75) is
"unsure" (present but not clearly abnormal), >=p75 is "fires". A pair's
overall verdict is the strongest tier reached by any of its three
dimensions; the agent's overall verdict is the strongest tier reached by
any pair. Severity scales with BOTH how far past threshold the worst
dimension is AND how many of the three dimensions are skewed at once
(a pair that's asymmetric on contrast AND area AND position is a
stronger signal than one skewed on a single axis alone).
"""

from typing import Dict, List, Optional, Tuple

from attribute_agents.base import AttributeAgent, no_result, scale_severity
from journey.baselines import Baseline, BaselineStore

AGENT_VERSION = "asymmetry_code/1.0.0"

_DIMENSIONS = ("contrast_ratio", "area_ratio", "position_delta")


def _pair_value(pair: Dict, dimension: str) -> Optional[float]:
    if dimension == "position_delta":
        value = pair.get("vertical_position_delta_px")
        return abs(value) if value is not None else None
    return pair.get(dimension)


def _dimension_tier(value: Optional[float], threshold: Baseline) -> Optional[str]:
    """None (clean), "unsure", or "fires" for one dimension of one pair."""
    if value is None:
        return None
    if value >= threshold.p75:
        return "fires"
    if value >= threshold.median:
        return "unsure"
    return None


def _pair_assessment(pair: Dict, thresholds: Dict[str, Baseline]) -> Tuple[Optional[str], List[str], float]:
    """Returns (tier, skewed_dimension_names, max_ratio_to_p75) for one pair."""
    tier = None
    skewed: List[str] = []
    max_ratio = 0.0

    for dimension in _DIMENSIONS:
        value = _pair_value(pair, dimension)
        dim_tier = _dimension_tier(value, thresholds[dimension])
        if dim_tier is None:
            continue
        skewed.append(dimension)
        if dim_tier == "fires":
            tier = "fires"
        elif dim_tier == "unsure" and tier != "fires":
            tier = "unsure"
        if value and thresholds[dimension].p75:
            max_ratio = max(max_ratio, value / thresholds[dimension].p75)

    return tier, skewed, max_ratio


def assess(episode: Dict, group_evidence: Optional[Dict], baselines: BaselineStore) -> Dict:
    pairs = (episode.get("evidence") or {}).get("visual_asymmetry") or []
    thresholds = {
        "contrast_ratio": baselines.get("asymmetry_contrast_ratio_threshold"),
        "area_ratio": baselines.get("asymmetry_area_ratio_threshold"),
        "position_delta": baselines.get("asymmetry_position_delta_px_threshold"),
    }

    assessed = [(pair, *_pair_assessment(pair, thresholds)) for pair in pairs]
    firing = [(pair, skewed, ratio) for pair, tier, skewed, ratio in assessed if tier == "fires"]
    unsure = [(pair, skewed, ratio) for pair, tier, skewed, ratio in assessed if tier == "unsure"]

    if not firing and not unsure:
        return no_result(
            f"No opposing-choice pair reached the asymmetry threshold on any dimension "
            f"(contrast/area/position) across {len(pairs)} pair(s)."
        )

    active = firing or unsure
    verdict = "fires" if firing else "unsure"

    evidence_pointers = []
    for pair, skewed, _ratio in active:
        for dimension in skewed:
            evidence_pointers.append(
                {"step_id": pair["step_id"], "selector": pair["positive_selector"], "signal": f"visual_asymmetry.{dimension}.positive"}
            )
            evidence_pointers.append(
                {"step_id": pair["step_id"], "selector": pair["negative_selector"], "signal": f"visual_asymmetry.{dimension}.negative"}
            )

    max_ratio = max(ratio for _, _, ratio in active)
    max_skew_breadth = max(len(skewed) for _, skewed, _ in active)
    base_severity = scale_severity(max_ratio, 1.0)  # max_ratio is already normalized to "x times p75"
    severity = min(5, base_severity + (max_skew_breadth - 1)) if verdict == "fires" else None

    reasons = []
    for pair, skewed, _ratio in active:
        reasons.append(f"pair at step {pair['step_id']} skewed on {', '.join(skewed)}")

    return {
        "verdict": verdict,
        "severity": severity,
        "confidence": 0.75 if verdict == "fires" else 0.5,
        "evidence_pointers": evidence_pointers,
        "reasoning": (
            f"{len(active)} of {len(pairs)} pair(s) {'exceeded' if verdict == 'fires' else 'approached'} "
            f"the asymmetry threshold: " + "; ".join(reasons) + "."
        ),
    }


AGENT = AttributeAgent(
    agent_id="asymmetry_code_v1",
    attribute="asymmetry",
    agent_version=AGENT_VERSION,
    agent_type="code",
    required_signals=["evidence.visual_asymmetry"],
    assess=assess,
)
