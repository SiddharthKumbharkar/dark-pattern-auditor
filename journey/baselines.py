"""Honest-site baseline distributions (Layer 2 -- file I/O, so this lives
here rather than in signals/).

baselines.json holds a median/p25/p75/n distribution per named signal.
Any group-evidence signal that needs a threshold (is this duration too
long to be plausible? is this timer drift too large?) reads it from here
-- never a literal number in signals/claim_persistence.py or
signals/timer_reset.py. See update_baselines.py for how the file gets
recomputed from real labelled-clean episode data; until that's been run
for a given key, this file's SEED values (below) are what's in use --
disclosed as reasonable starting points, not empirically derived numbers.
"""

import json
import os
import statistics
from dataclasses import dataclass
from typing import Dict, List, Optional

from config.settings import PROJECT_ROOT

DEFAULT_BASELINES_PATH = os.path.join(PROJECT_ROOT, "baselines.json")

# Seed values, shipped so the file always has something to read (a group
# signal must never fall back to a hardcoded number when a baseline key
# is simply missing from the file). n=0 marks a seed as not yet backed by
# real labelled-clean data -- see BaselineStore.is_seed().
_SEED_BASELINES: Dict[str, Dict] = {
    "claim_unchanged_hours_before_implausible": {
        "median": 24.0, "p25": 12.0, "p75": 48.0, "n": 0,
        "description": "Hours a non-timer claim (stock count, deadline phrase, etc.) can stay byte-identical before that's treated as implausible for a live, genuine claim.",
    },
    "timer_drift_tolerance_seconds": {
        "median": 30.0, "p25": 10.0, "p75": 60.0, "n": 0,
        "description": "How far a countdown's observed remaining-time may deviate from (previous remaining - elapsed wall clock) before being treated as a reset rather than capture-timing noise.",
    },
    "claim_min_elapsed_hours_for_verdict": {
        "median": 1.0, "p25": 0.5, "p75": 4.0, "n": 0,
        "description": "Minimum elapsed time between a claim's first and last observed revisit before a verdict is attempted at all -- below this, verdict is always insufficient_data.",
    },
    # -- attribute_agents/ thresholds (Phase 3) --------------------------
    "asymmetry_contrast_ratio_threshold": {
        "median": 3.0, "p25": 2.0, "p75": 4.5, "n": 0,
        "description": "Distribution of visual_asymmetry.contrast_ratio; attribute_agents/asymmetry.py fires at/above p75, is unsure in [median, p75).",
    },
    "asymmetry_area_ratio_threshold": {
        "median": 2.0, "p25": 1.5, "p75": 3.0, "n": 0,
        "description": "Distribution of visual_asymmetry.area_ratio; same fires/unsure tiering as asymmetry_contrast_ratio_threshold.",
    },
    "asymmetry_position_delta_px_threshold": {
        "median": 150.0, "p25": 80.0, "p75": 300.0, "n": 0,
        "description": "Distribution of |visual_asymmetry.vertical_position_delta_px|; the third dimension attribute_agents/asymmetry.py checks alongside contrast and area.",
    },
    # covertness_contrast_ratio_threshold: unused since attribute_agents/covertness.py
    # was replaced with an explicit not_assessable stub pending Stage 2 LLM
    # judgement -- left in place (harmless, dormant) rather than deleted,
    # since a future Stage 2 agent may still want it.
    "covertness_contrast_ratio_threshold": {
        "median": 5.0, "p25": 3.5, "p75": 7.0, "n": 0,
        "description": "UNUSED as of the covertness stub (Stage 2, LLM judgement) -- kept for a future LLM-backed covertness agent.",
    },
    # information_hiding_price_increase_ratio_threshold: unused for the same
    # reason (attribute_agents/information_hiding.py is now a stub).
    "information_hiding_price_increase_ratio_threshold": {
        "median": 0.05, "p25": 0.02, "p75": 0.12, "n": 0,
        "description": "UNUSED as of the information_hiding stub (Stage 2, LLM judgement) -- kept for a future LLM-backed agent.",
    },
    "restriction_friction_ratio_threshold": {
        "median": 1.5, "p25": 1.2, "p75": 2.0, "n": 0,
        "description": "Distribution of friction_metrics.friction_ratio; attribute_agents/restriction.py fires at/above p75*restriction_p75_factor, is unsure in [p75, p75*factor).",
    },
    "restriction_p75_factor": {
        "median": 1.3, "p25": 1.15, "p75": 1.5, "n": 0,
        "description": "Multiplier applied to a distribution's p75 before attribute_agents/restriction.py commits to 'fires' rather than 'unsure' -- the task's 'configurable factor'.",
    },
    "restriction_forced_interstitial_count_threshold": {
        "median": 1.0, "p25": 0.0, "p75": 2.0, "n": 0,
        "description": "Distribution of forced_interstitial event counts (evidence.path_deviation) for a paired episode; attribute_agents/restriction.py's second, independent firing path alongside friction_ratio.",
    },
    # disparate_treatment_ratio_threshold: unused for the same reason
    # (attribute_agents/disparate_treatment.py is now a stub).
    "disparate_treatment_ratio_threshold": {
        "median": 1.5, "p25": 1.2, "p75": 2.0, "n": 0,
        "description": "UNUSED as of the disparate_treatment stub (Stage 2, LLM judgement) -- kept for a future LLM-backed agent.",
    },
    "complexity_reading_grade_threshold": {
        "median": 12.0, "p25": 10.0, "p75": 14.0, "n": 0,
        "description": "Global default distribution of Flesch-Kincaid grade level for consent/cancellation copy. Goal-scoped overrides (\"complexity_reading_grade_threshold::<goal_id>\") are tried first by attribute_agents/complexity.py -- see e.g. the cancel_subscription entry below -- so inherent per-goal complexity isn't measured against an unrelated goal's norm.",
    },
    "complexity_reading_grade_threshold::cancel_subscription": {
        "median": 14.0, "p25": 11.0, "p75": 17.0, "n": 0,
        "description": "Goal-scoped override for cancel_subscription: cancellation copy tends to run denser than the global default even on honest sites (terms/legal framing), so the same absolute grade level means less on this goal specifically.",
    },
    "complexity_option_count_threshold": {
        "median": 4.0, "p25": 2.0, "p75": 7.0, "n": 0,
        "description": "Distribution of complexity_metrics.option_counts[].option_count per decision point; goal-scoped lookups supported the same way as complexity_reading_grade_threshold.",
    },
    "complexity_total_actions_threshold": {
        "median": 6.0, "p25": 3.0, "p75": 10.0, "n": 0,
        "description": "Distribution of complexity_metrics.total_actions_required; goal-scoped lookups supported the same way as complexity_reading_grade_threshold.",
    },
    "deception_min_evidence_count": {
        "median": 1.0, "p25": 1.0, "p75": 2.0, "n": 0,
        "description": "Minimum count of implausible claims/timer resets/no-network state-change actions needed for attribute_agents/deception.py to fire -- 1 means any single occurrence is enough.",
    },
}


@dataclass(frozen=True)
class Baseline:
    median: float
    p25: float
    p75: float
    n: int
    description: str = ""

    def is_seed(self) -> bool:
        return self.n == 0


class BaselineStore:
    def __init__(self, path: Optional[str] = None):
        self.path = path or DEFAULT_BASELINES_PATH
        self._data: Dict[str, Dict] = self._load()

    def _load(self) -> Dict[str, Dict]:
        if os.path.isfile(self.path):
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        return dict(_SEED_BASELINES)

    def get(self, key: str, goal: Optional[str] = None) -> Baseline:
        """Never raises for a key with no on-disk entry -- falls back to
        the shipped seed so callers always get a usable threshold.

        goal: some attributes (see attribute_agents/complexity.py) need to
        judge a signal against what's NORMAL FOR THAT GOAL, not a single
        global distribution -- a cancel flow's inherent option count/
        reading level isn't directly comparable to a signup flow's. When
        goal is given, a goal-qualified entry ("<key>::<goal>") is tried
        FIRST; if none has been calibrated yet (see update_baselines.py),
        this falls back to the global <key> rather than failing, so a
        goal-scoped lookup never has a harder failure mode than a plain one.
        """
        entry = None
        if goal:
            entry = self._data.get(f"{key}::{goal}")
        if entry is None:
            entry = self._data.get(key) or _SEED_BASELINES.get(key)
        if entry is None:
            raise KeyError(
                f"no baseline for {key!r} and no seed default -- add one to "
                f"journey.baselines._SEED_BASELINES"
            )
        return Baseline(
            median=entry["median"], p25=entry["p25"], p75=entry["p75"],
            n=entry["n"], description=entry.get("description", ""),
        )

    def set_from_samples(
        self, key: str, samples: List[float], description: str = "", goal: Optional[str] = None
    ) -> Baseline:
        if not samples:
            raise ValueError(f"cannot compute a baseline for {key!r} from zero samples")
        storage_key = f"{key}::{goal}" if goal else key
        sorted_samples = sorted(samples)
        baseline = Baseline(
            median=statistics.median(sorted_samples),
            p25=_percentile(sorted_samples, 25),
            p75=_percentile(sorted_samples, 75),
            n=len(sorted_samples),
            description=description or self._data.get(storage_key, {}).get("description", ""),
        )
        self._data[storage_key] = {
            "median": baseline.median, "p25": baseline.p25, "p75": baseline.p75,
            "n": baseline.n, "description": baseline.description,
        }
        return baseline

    def save(self) -> None:
        tmp_path = self.path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, sort_keys=True)
        os.replace(tmp_path, self.path)

    def keys(self) -> List[str]:
        return sorted(set(self._data.keys()) | set(_SEED_BASELINES.keys()))


def _percentile(sorted_values: List[float], pct: float) -> float:
    """Linear-interpolation percentile (the common, simple definition --
    no numpy dependency needed for this)."""
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (pct / 100) * (len(sorted_values) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(sorted_values) - 1)
    fraction = rank - lower
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * fraction
