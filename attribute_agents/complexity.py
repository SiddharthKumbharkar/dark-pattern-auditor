"""complexity: is a decision point overloaded with options, is consent/
cancellation copy written at an unreasonably high reading grade, or does
the flow require an unusually large number of distinct actions? Code
agent, pure function over episode.evidence.complexity_metrics
(signals/complexity.py).

Every threshold is looked up SCOPED TO THIS EPISODE'S GOAL first
(baselines.get(key, goal=episode_goal)), falling back to the global
default only if no goal-specific baseline has been calibrated yet -- a
cancel_subscription flow's inherent option count/reading level isn't
directly comparable to a signup flow's, so judging both against one
global number would conflate complexity IMPOSED by the flow (a candidate
dark pattern) with complexity that's simply INHERENT to that particular
task. See journey/baselines.py's goal-scoping mechanism and the seeded
"complexity_reading_grade_threshold::cancel_subscription" entry.

Three independently-assessable dimensions: a dimension is skipped
entirely (contributes neither "fires" nor "no") when its own source data
is empty -- e.g. no consent/cancellation copy existed on the page at all,
so there's nothing to grade. The agent's overall verdict is the
strongest tier reached by any assessable dimension; not_assessable only
if NONE of the three had anything to measure.
"""

from typing import Dict, List, Optional, Tuple

from attribute_agents.base import AttributeAgent, not_assessable_result, scale_severity
from journey.baselines import Baseline, BaselineStore

AGENT_VERSION = "complexity_code/1.0.0"


def _tier(value: float, threshold: Baseline) -> Optional[str]:
    if value >= threshold.p75:
        return "fires"
    if value >= threshold.median:
        return "unsure"
    return None


def _option_count_dimension(complexity_metrics: Dict, goal: Optional[str], baselines: BaselineStore) -> Optional[Tuple]:
    option_counts = complexity_metrics.get("option_counts") or []
    if not option_counts:
        return None
    threshold = baselines.get("complexity_option_count_threshold", goal=goal)
    worst = max(option_counts, key=lambda o: o["option_count"])
    tier = _tier(worst["option_count"], threshold)
    if tier is None:
        return None
    pointer = {"step_id": worst["step_id"], "selector": None, "signal": "complexity_metrics.option_counts.option_count"}
    ratio = (worst["option_count"] / threshold.p75) if threshold.p75 else 1.0
    detail = f"option_count={worst['option_count']} at step {worst['step_id']}"
    return "option_count", tier, [pointer], ratio, detail


def _reading_level_dimension(complexity_metrics: Dict, goal: Optional[str], baselines: BaselineStore) -> Optional[Tuple]:
    copy_readability = complexity_metrics.get("copy_readability") or []
    graded = [r for r in copy_readability if r.get("flesch_kincaid_grade") is not None]
    if not graded:
        return None
    threshold = baselines.get("complexity_reading_grade_threshold", goal=goal)
    worst = max(graded, key=lambda r: r["flesch_kincaid_grade"])
    tier = _tier(worst["flesch_kincaid_grade"], threshold)
    if tier is None:
        return None
    pointer = {"step_id": worst["step_id"], "selector": None, "signal": "complexity_metrics.copy_readability.flesch_kincaid_grade"}
    ratio = (worst["flesch_kincaid_grade"] / threshold.p75) if threshold.p75 else 1.0
    detail = f"reading grade={worst['flesch_kincaid_grade']:.1f} at step {worst['step_id']}"
    return "reading_level", tier, [pointer], ratio, detail


def _total_actions_dimension(complexity_metrics: Dict, goal: Optional[str], baselines: BaselineStore) -> Optional[Tuple]:
    total_actions = complexity_metrics.get("total_actions_required")
    if total_actions is None:
        return None
    threshold = baselines.get("complexity_total_actions_threshold", goal=goal)
    tier = _tier(float(total_actions), threshold)
    if tier is None:
        return None
    pointer = {"step_id": None, "selector": None, "signal": "complexity_metrics.total_actions_required"}
    ratio = (total_actions / threshold.p75) if threshold.p75 else 1.0
    detail = f"total_actions_required={total_actions}"
    return "total_actions", tier, [pointer], ratio, detail


def assess(episode: Dict, group_evidence: Optional[Dict], baselines: BaselineStore) -> Dict:
    complexity_metrics = (episode.get("evidence") or {}).get("complexity_metrics") or {}
    goal = (episode.get("episode") or {}).get("goal")

    has_any_source = bool(complexity_metrics.get("option_counts")) or bool(complexity_metrics.get("copy_readability")) \
        or complexity_metrics.get("total_actions_required") is not None
    if not has_any_source:
        return not_assessable_result(
            "complexity_metrics has no option counts, no consent/cancellation copy, and no "
            "total_actions_required to assess."
        )

    dimensions = [
        d
        for d in (
            _option_count_dimension(complexity_metrics, goal, baselines),
            _reading_level_dimension(complexity_metrics, goal, baselines),
            _total_actions_dimension(complexity_metrics, goal, baselines),
        )
        if d is not None
    ]

    if not dimensions:
        option_counts = complexity_metrics.get("option_counts") or []
        copy_readability = complexity_metrics.get("copy_readability") or []
        total_actions = complexity_metrics.get("total_actions_required")
        return {
            "verdict": "no",
            "severity": None,
            "confidence": 0.7,
            "evidence_pointers": [],
            "reasoning": (
                f"Checked {len(option_counts)} option-count sample(s), {len(copy_readability)} copy block(s), "
                f"total_actions_required={total_actions}; none reached the {goal or 'global'} complexity threshold."
            ),
        }

    verdict = "fires" if any(tier == "fires" for _, tier, _, _, _ in dimensions) else "unsure"
    evidence_pointers: List[Dict] = [pointer for _, _, pointers, _, _ in dimensions for pointer in pointers]
    max_ratio = max(ratio for _, _, _, ratio, _ in dimensions)
    severity = scale_severity(max_ratio, 1.0) if verdict == "fires" else None
    reasons = [detail for _, _, _, _, detail in dimensions]

    return {
        "verdict": verdict,
        "severity": severity,
        "confidence": 0.75 if verdict == "fires" else 0.5,
        "evidence_pointers": evidence_pointers,
        "reasoning": (
            f"{len(dimensions)} dimension(s) {'exceeded' if verdict == 'fires' else 'approached'} the "
            f"{goal or 'global'} complexity threshold: " + "; ".join(reasons) + "."
        ),
    }


AGENT = AttributeAgent(
    agent_id="complexity_code_v1",
    attribute="complexity",
    agent_version=AGENT_VERSION,
    agent_type="code",
    required_signals=["evidence.complexity_metrics"],
    assess=assess,
)
