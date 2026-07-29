"""Compares an episode's actual attribute verdicts against
ground_truth.yaml's expected findings, at the attribute level -- the
known-answer test for the Auralis demo site (or any site described by a
similarly-shaped ground_truth.yaml). Layer 2: reads ground_truth.yaml and
an already-processed (evidence + attributes already run) episode from
disk; no I/O beyond that, no browser, no LLM.

Mode (on/off) is auto-detected from episode.episode.site_domain using
this harness's convention -- see ground_truth.yaml's header comment and
run_demo_suite.py: ON and OFF sessions are recorded against the SAME
dev server/URL, but record.py's --site-domain flag independently labels
the episode's site_domain metadata "auralis-on.local"/"auralis-off.local"
(site_domain is pure metadata, decoupled from the actual connection host
-- it does not need to be a resolvable hostname). This is deliberately
NOT "localhost vs 127.0.0.1": some dev servers (Next.js's, in
particular) reject requests carrying a 127.0.0.1 Host header outright,
so relying on the server accepting an alternate real host is fragile;
labeling via --site-domain works against any dev server. Pass mode
explicitly to override when an episode wasn't recorded under this
convention.
"""

import os
from typing import Dict, List, Optional

import yaml

from attribute_agents.base import ATTRIBUTES

REQUIRED_PATTERN_FIELDS = {
    "pattern_id", "name", "ccpa_category", "goal", "expected_steps_hint",
    "expected_attributes", "enabled_when", "requires_revisit", "known_gap",
}

# This harness's on/off recording convention (see module docstring and
# ground_truth.yaml). Not a generic config value -- it's specific to how
# run_demo_suite.py drives the Auralis dev server, so it's a constant here
# rather than something config.yaml needs to know about.
SITE_DOMAIN_TO_MODE = {"auralis-on.local": "on", "auralis-off.local": "off"}


class GroundTruthError(ValueError):
    """ground_truth.yaml is malformed, or an episode's mode couldn't be
    determined -- always a clear, actionable message."""


def load_ground_truth(path: str) -> Dict:
    if not os.path.isfile(path):
        raise GroundTruthError(f"ground truth file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    if not isinstance(doc, dict) or not isinstance(doc.get("patterns"), list):
        raise GroundTruthError(f"{path} must be a mapping with a top-level 'patterns' list")

    for i, pattern in enumerate(doc["patterns"]):
        if not isinstance(pattern, dict):
            raise GroundTruthError(f"{path}: patterns[{i}] must be a mapping")
        missing = REQUIRED_PATTERN_FIELDS - set(pattern.keys())
        if missing:
            raise GroundTruthError(f"{path}: patterns[{i}] missing field(s): {sorted(missing)}")
        if not isinstance(pattern["expected_attributes"], list):
            raise GroundTruthError(f"{path}: patterns[{i}] expected_attributes must be a list")
        unknown = [a for a in pattern["expected_attributes"] if a not in ATTRIBUTES]
        if unknown:
            raise GroundTruthError(
                f"{path}: patterns[{i}] ({pattern['pattern_id']!r}) names unknown attribute(s) {unknown} "
                f"-- must be one of {ATTRIBUTES}"
            )
        if pattern["enabled_when"] != "on":
            raise GroundTruthError(
                f"{path}: patterns[{i}] ({pattern['pattern_id']!r}) has enabled_when={pattern['enabled_when']!r}, "
                f'only "on" is currently supported (every planted pattern is absent entirely when the toggle is off).'
            )

    ids = [p["pattern_id"] for p in doc["patterns"]]
    if len(ids) != len(set(ids)):
        raise GroundTruthError(f"{path}: duplicate pattern_id(s) in patterns list")

    return doc


def infer_mode(episode: Dict) -> Optional[str]:
    site_domain = (episode.get("episode") or {}).get("site_domain")
    return SITE_DOMAIN_TO_MODE.get(site_domain)


def _applicable_patterns(ground_truth: Dict, goal: Optional[str]) -> List[Dict]:
    """A pattern with goal: null applies regardless of which goal this
    episode is pursuing (the global/passive patterns -- popups that fire
    on any page); a pattern with a goal only applies to episodes pursuing
    that exact goal."""
    return [p for p in ground_truth["patterns"] if p["goal"] is None or p["goal"] == goal]


def _expected_attributes(ground_truth: Dict, goal: Optional[str], mode: str) -> set:
    if mode == "off":
        return set()  # nothing is planted at all when the toggle is off
    expected = set()
    for pattern in _applicable_patterns(ground_truth, goal):
        expected.update(pattern["expected_attributes"])
    return expected


def _miss_notes(ground_truth: Dict, goal: Optional[str], attribute: str) -> str:
    reasons = []
    for pattern in _applicable_patterns(ground_truth, goal):
        if attribute not in pattern["expected_attributes"]:
            continue
        if pattern.get("known_gap"):
            reasons.append(f"{pattern['pattern_id']}: {pattern['known_gap']}")
        elif pattern.get("requires_revisit"):
            reasons.append(
                f"{pattern['pattern_id']}: requires revisit data (claim_persistence/timer_reset_detection) "
                f"-- check this episode's group_evidence_path points at a group with 2+ visits."
            )
        else:
            reasons.append(f"{pattern['pattern_id']}: expected but not explained by a known gap -- worth investigating.")
    return "; ".join(reasons)


def validate_against_truth(episode: Dict, ground_truth: Dict, mode: Optional[str] = None) -> Dict:
    """Pure function: no file I/O of its own (episode and ground_truth are
    already-loaded dicts). Returns a dict with a per-attribute row list
    plus precision/recall/f1 computed from the 7-attribute confusion
    matrix (TP/FP/FN/TN), each None when its denominator is zero rather
    than a misleading 0.0/1.0."""
    resolved_mode = mode or infer_mode(episode)
    if resolved_mode not in ("on", "off"):
        episode_id = (episode.get("episode") or {}).get("episode_id")
        site_domain = (episode.get("episode") or {}).get("site_domain")
        raise GroundTruthError(
            f"could not determine on/off mode for episode {episode_id!r} (site_domain={site_domain!r}) -- "
            f"pass mode explicitly, or record it under this harness's localhost(on)/127.0.0.1(off) convention."
        )

    goal = (episode.get("episode") or {}).get("goal")
    expected = _expected_attributes(ground_truth, goal, resolved_mode)
    results_by_attribute = {r["attribute"]: r for r in ((episode.get("attributes") or {}).get("results") or [])}

    rows = []
    tp = fp = fn = tn = 0
    for attribute in ATTRIBUTES:
        is_expected = attribute in expected
        code_result = results_by_attribute.get(attribute)
        code_verdict = code_result["verdict"] if code_result else None
        is_detected = code_verdict == "fires"

        if is_expected and is_detected:
            classification = "TP"
            tp += 1
        elif is_expected and not is_detected:
            classification = "FN"
            fn += 1
        elif not is_expected and is_detected:
            classification = "FP"
            fp += 1
        else:
            classification = "TN"
            tn += 1

        notes = _miss_notes(ground_truth, goal, attribute) if classification == "FN" else ""

        rows.append({
            "attribute": attribute,
            "expected": is_expected,
            "code_verdict": code_verdict,
            "detected": is_detected,
            "classification": classification,
            "notes": notes,
        })

    precision = tp / (tp + fp) if (tp + fp) > 0 else None
    recall = tp / (tp + fn) if (tp + fn) > 0 else None
    if precision is not None and recall is not None and (precision + recall) > 0:
        f1 = 2 * precision * recall / (precision + recall)
    else:
        f1 = None

    return {
        "episode_id": (episode.get("episode") or {}).get("episode_id"),
        "goal": goal,
        "mode": resolved_mode,
        "rows": rows,
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": precision, "recall": recall, "f1": f1,
    }
