"""Countdown-timer reset detection across an episode group's revisits
(Layer 3). Pure measurement: does the observed remaining-time track real
wall-clock elapsed time, or does it fail to decrease -- the classic fake-
countdown pattern where "2 hours left" shows no matter when you visit.

Tolerance for capture-timing noise comes from journey/baselines.py, not a
literal number here.
"""

from datetime import datetime
from typing import Dict, List, Optional

from journey.baselines import Baseline


def _elapsed_seconds(earlier_iso: str, later_iso: str) -> Optional[float]:
    try:
        earlier = datetime.fromisoformat(earlier_iso)
        later = datetime.fromisoformat(later_iso)
    except (ValueError, TypeError):
        return None
    return (later - earlier).total_seconds()


def compute_timer_drifts(revisits: List[Dict]) -> List[float]:
    """Raw |observed - expected| deviation magnitudes, with no
    classification applied -- what update_baselines.py uses to derive
    timer_drift_tolerance_seconds from labelled-clean sites' own
    (presumed genuinely functioning) countdown timers."""
    drifts = []
    for earlier, later in zip(revisits, revisits[1:]):
        elapsed = _elapsed_seconds(earlier["timestamp"], later["timestamp"])
        earlier_remaining = earlier.get("remaining_seconds")
        later_remaining = later.get("remaining_seconds")
        if elapsed is None or earlier_remaining is None or later_remaining is None:
            continue
        expected_remaining = max(0.0, earlier_remaining - elapsed)
        drifts.append(abs(later_remaining - expected_remaining))
    return drifts


def detect_timer_resets(revisits: List[Dict], tolerance: Baseline) -> List[Dict]:
    """revisits: [{"revisit_index": int, "timestamp": str,
    "remaining_seconds": int}], sorted by revisit_index (one entry per
    revisit where this same countdown_timer claim identity was observed
    -- see signals.claim_persistence.group_claims_by_identity). Returns
    one comparison record per consecutive pair of revisits."""
    results = []
    for earlier, later in zip(revisits, revisits[1:]):
        elapsed = _elapsed_seconds(earlier["timestamp"], later["timestamp"])
        earlier_remaining = earlier.get("remaining_seconds")
        later_remaining = later.get("remaining_seconds")
        if elapsed is None or earlier_remaining is None or later_remaining is None:
            continue

        expected_remaining = max(0.0, earlier_remaining - elapsed)
        reset_detected = later_remaining > expected_remaining + tolerance.median

        results.append(
            {
                "from_revisit_index": earlier["revisit_index"],
                "to_revisit_index": later["revisit_index"],
                "elapsed_seconds": round(elapsed, 1),
                "expected_remaining_seconds": round(expected_remaining, 1),
                "observed_remaining_seconds": later_remaining,
                "reset_detected": reset_detected,
            }
        )
    return results
