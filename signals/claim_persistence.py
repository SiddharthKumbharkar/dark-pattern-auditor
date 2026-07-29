"""Cross-episode claim persistence (Layer 3). Pure measurement: joins
claims by (claim_type, selector) identity across an episode group's
revisits, and measures whether the observed pattern of change (or
non-change) is plausible for that claim type.

Never outputs "false" -- only "verified_true" | "implausible" |
"insufficient_data". We measure whether a pattern is consistent with a
genuine, live claim; we do not (and structurally cannot, from browser
observation alone) prove a claim is false -- the same epistemic stance
prompts/pattern_prompt_judge.txt already takes for single-episode
temporal_checks ("scarcity claim persisted across sessions", never
"claim is false").

Thresholds (how long unchanged is "too long", how much elapsed time is
"enough to judge") come from journey/baselines.py -- Baseline objects
passed in by the caller (journey/group_evidence_extractor.py), never a
literal number here.
"""

from datetime import datetime
from typing import Dict, List, Optional, Tuple

from journey.baselines import Baseline

_MONOTONIC_DECREASE_TYPES = {"stock_count"}


def _claim_identity(claim: Dict) -> Optional[Tuple[str, str]]:
    if not claim.get("selector"):
        return None
    return (claim["claim_type"], claim["selector"])


def group_claims_by_identity(episodes_claims: List[Dict]) -> Dict[Tuple[str, str], List[Dict]]:
    """episodes_claims: [{"revisit_index": int, "timestamp": str, "claims": [...]}],
    where each "claims" entry is one episode's evidence.claim_extraction.

    Returns {(claim_type, selector): [{"revisit_index", "timestamp",
    "claim_text", "normalized_value"}, ...]}, sorted by revisit_index.
    A claim with no selector can't be joined across episodes and is
    dropped, not guessed at.
    """
    grouped: Dict[Tuple[str, str], List[Dict]] = {}
    for entry in episodes_claims:
        for claim in entry.get("claims") or []:
            identity = _claim_identity(claim)
            if identity is None:
                continue
            grouped.setdefault(identity, []).append(
                {
                    "revisit_index": entry["revisit_index"],
                    "timestamp": entry["timestamp"],
                    "claim_text": claim["claim_text"],
                    "normalized_value": claim["normalized_value"],
                }
            )
    for identity, revisits in grouped.items():
        revisits.sort(key=lambda r: r["revisit_index"])
    return grouped


def _elapsed_hours(revisits: List[Dict]) -> Optional[float]:
    if len(revisits) < 2:
        return None
    try:
        first = datetime.fromisoformat(revisits[0]["timestamp"])
        last = datetime.fromisoformat(revisits[-1]["timestamp"])
    except (ValueError, TypeError):
        return None
    return (last - first).total_seconds() / 3600


def _is_unchanged(revisits: List[Dict]) -> bool:
    signature = [(r["normalized_value"], r["claim_text"]) for r in revisits]
    return all(s == signature[0] for s in signature)


def _judge_plausibility(
    claim_type: str, values: List, unchanged: bool, elapsed_hours: float, unchanged_threshold: Baseline
) -> bool:
    frozen_too_long = unchanged and elapsed_hours >= unchanged_threshold.median

    if claim_type in _MONOTONIC_DECREASE_TYPES:
        numeric_values = [v for v in values if v is not None]
        if len(numeric_values) >= 2:
            if numeric_values[-1] < numeric_values[0]:
                return True  # genuinely depleting -- plausible regardless of duration
            if numeric_values[-1] > numeric_values[0]:
                return False  # "limited stock" claim went UP -- implausible
        return not frozen_too_long

    # countdown_timer, viewer_count, purchase_count, deadline_phrase,
    # urgency_phrase, social_proof: no monotonic expectation, so the only
    # measurable red flag is "identical for far longer than an honest
    # site's typical claim lifetime" -- see signals/timer_reset.py for the
    # more precise wall-clock-vs-remaining-time check specific to timers.
    return not frozen_too_long


def evaluate_claim_persistence(
    claim_type: str,
    selector: str,
    revisits: List[Dict],
    unchanged_threshold: Baseline,
    min_elapsed_threshold: Baseline,
) -> Dict:
    unchanged = _is_unchanged(revisits)
    elapsed_hours = _elapsed_hours(revisits)

    has_enough_data = (
        len(revisits) >= 2 and elapsed_hours is not None and elapsed_hours >= min_elapsed_threshold.median
    )

    if not has_enough_data:
        plausible_change = None
        verdict = "insufficient_data"
    else:
        plausible_change = _judge_plausibility(
            claim_type, [r["normalized_value"] for r in revisits], unchanged, elapsed_hours, unchanged_threshold
        )
        verdict = "verified_true" if plausible_change else "implausible"

    return {
        "claim_type": claim_type,
        "selector": selector,
        "revisit_indices": [r["revisit_index"] for r in revisits],
        "values": [r["normalized_value"] for r in revisits],
        "claim_texts": [r["claim_text"] for r in revisits],
        "elapsed_hours": round(elapsed_hours, 2) if elapsed_hours is not None else None,
        "unchanged_across_revisits": unchanged,
        # Nullable, not strictly bool: with insufficient data there is
        # genuinely no plausibility judgement to report either way --
        # forcing a True/False here would itself be an unmeasured
        # conclusion, which is exactly what this module exists to avoid.
        "plausible_change": plausible_change,
        "verdict": verdict,
    }


def compute_claim_persistence(episodes_claims: List[Dict], unchanged_threshold: Baseline, min_elapsed_threshold: Baseline) -> List[Dict]:
    grouped = group_claims_by_identity(episodes_claims)
    results = []
    for (claim_type, selector), revisits in grouped.items():
        results.append(
            evaluate_claim_persistence(claim_type, selector, revisits, unchanged_threshold, min_elapsed_threshold)
        )
    return results
