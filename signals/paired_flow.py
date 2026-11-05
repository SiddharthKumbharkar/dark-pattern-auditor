"""Side-by-side comparison of a linked episode pair (e.g. signup vs
cancel) -- pure measurement over each episode's already-computed
friction_metrics (Layer 3). No new capture, no re-derivation: this is
literally last turn's per-episode friction_metrics, presented pairwise.
"""

from typing import Dict, Optional


def _ratio(a: float, b: float) -> Optional[float]:
    return (a / b) if b else None


def compare_paired_flows(episode_a_id: str, episode_b_id: str, friction_a: Dict, friction_b: Dict) -> Dict:
    return {
        "episode_a_id": episode_a_id,
        "episode_b_id": episode_b_id,
        "steps": {"a": friction_a["steps"], "b": friction_b["steps"]},
        "clicks": {"a": friction_a["clicks"], "b": friction_b["clicks"]},
        "fields": {"a": friction_a["form_fields_required"], "b": friction_b["form_fields_required"]},
        "interstitials": {"a": friction_a["confirmation_interstitials"], "b": friction_b["confirmation_interstitials"]},
        "ratios": {
            "steps_ratio": _ratio(friction_a["steps"], friction_b["steps"]),
            "clicks_ratio": _ratio(friction_a["clicks"], friction_b["clicks"]),
            "fields_ratio": _ratio(friction_a["form_fields_required"], friction_b["form_fields_required"]),
            "interstitials_ratio": _ratio(
                friction_a["confirmation_interstitials"], friction_b["confirmation_interstitials"]
            ),
        },
    }
