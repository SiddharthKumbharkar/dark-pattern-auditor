"""Reads a stored (masked) episode and computes episode.evidence (Layer 2).

Pure measurement over already-persisted artifacts -- no browser, no LLM,
no re-recording. Every signals/*.py function this module calls is a pure
function over plain data; this module is the only place in the evidence
path that reads files from disk and assembles/writes the result, which is
why the file I/O lives here and not in signals/ (Layer 3's "no file I/O"
rule -- see CLAUDE.md).

Idempotent: extract_evidence() always REPLACES episode["evidence"]
wholesale (never merges/appends into whatever was there before), so
re-running it against the same stored episode produces byte-identical
output every time, with no re-recording involved.
"""

import json
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

from journey.schema_migration import load_episode, validate_v2
from signals.claims import extract_claims
from signals.complexity import compute_complexity_metrics
from signals.dom_text import extract_text_candidates, full_text
from signals.friction import compute_friction_metrics
from signals.path_deviation import compute_path_deviation
from signals.price_drift import compute_price_drift
from signals.stated_vs_actual import find_stated_vs_actual
from signals.ui_regions import compute_ui_regions
from signals.visual_asymmetry import compute_visual_asymmetry

EXTRACTOR_VERSION = "evidence_extractor/1.0.0"


def _resolve_episode_json_path(path: str) -> str:
    if os.path.isdir(path):
        return os.path.join(path, "episode.json")
    return path


def _read_text_file(path: Optional[str]) -> Optional[str]:
    if not path or not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _read_json_file(path: Optional[str]) -> Optional[List[Dict]]:
    if not path or not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _step_artifact_path(episode_dir: str, step: Dict, key: str) -> Optional[str]:
    relative = step.get(key)
    return os.path.join(episode_dir, relative) if relative else None


def _paired_step_count(episode: Dict, storage_dir: str) -> Optional[int]:
    paired_id = (episode.get("episode") or {}).get("paired_episode_id")
    if not paired_id:
        return None
    paired_path = os.path.join(storage_dir, paired_id, "episode.json")
    if not os.path.isfile(paired_path):
        return None
    try:
        with open(paired_path, "r", encoding="utf-8") as f:
            paired = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    return len(paired.get("steps") or [])


def extract_evidence(episode_path: str, storage_dir: Optional[str] = None) -> Dict:
    """episode_path: an episode.json file, or its containing directory.
    storage_dir: where sibling episodes (for friction_ratio's paired
    episode) live; defaults to episode_path's grandparent directory
    (i.e. output.root, since episodes live at output.root/<episode_id>/)."""
    # load_episode() migrates a v1 file to v2 in memory (see
    # journey/schema_migration.py); writing the result back means running
    # this against a v1 journey.json upgrades it to v2 on disk as a side
    # effect. That's an intentional consequence of reusing the v2 loader
    # for its validation guarantees, not an accident -- a v1 file has no
    # masked artifacts for evidence to measure anyway, so nearly every
    # signal below will legitimately come back empty/null for one.
    episode_json_path = _resolve_episode_json_path(episode_path)
    episode_dir = os.path.dirname(episode_json_path)
    if storage_dir is None:
        storage_dir = os.path.dirname(episode_dir)

    episode = load_episode(episode_json_path)
    steps: List[Dict] = episode.get("steps") or []

    dom_htmls = [
        _read_text_file(_step_artifact_path(episode_dir, step, "dom_snapshot_masked_path")) for step in steps
    ]
    computed_styles = [
        _read_json_file(_step_artifact_path(episode_dir, step, "computed_styles_path")) for step in steps
    ]
    page_texts = [full_text(html) if html else None for html in dom_htmls]
    computed_styles_by_step_id = {
        step["step_id"]: elements for step, elements in zip(steps, computed_styles) if elements is not None
    }

    friction_metrics = compute_friction_metrics(
        steps, dom_htmls, _paired_step_count(episode, storage_dir)
    )

    visual_asymmetry: List[Dict] = []
    for step, elements in zip(steps, computed_styles):
        if elements:
            visual_asymmetry.extend(compute_visual_asymmetry(step["step_id"], elements))

    claim_extraction: List[Dict] = []
    for step, html in zip(steps, dom_htmls):
        if html:
            claim_extraction.extend(extract_claims(step["step_id"], extract_text_candidates(html)))

    price_drift = compute_price_drift(
        [{"step_id": step["step_id"], "page_text": text} for step, text in zip(steps, page_texts) if text]
    )

    path_deviation = compute_path_deviation(steps, dom_htmls)

    interactive_counts = [len(elements) if elements is not None else None for elements in computed_styles]
    complexity_metrics = compute_complexity_metrics(steps, page_texts, interactive_counts)

    stated_vs_actual = find_stated_vs_actual(steps, computed_styles_by_step_id)

    # Region tagging runs here -- BEFORE any attribute agent -- so every
    # agent (and the coordinator) reads a region off an evidence_pointer
    # rather than classifying one itself. See signals/ui_regions.py.
    ui_regions = compute_ui_regions(steps, dom_htmls, computed_styles)

    evidence = {
        "extractor_version": EXTRACTOR_VERSION,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "friction_metrics": friction_metrics,
        "visual_asymmetry": visual_asymmetry,
        "claim_extraction": claim_extraction,
        "price_drift": price_drift,
        "path_deviation": path_deviation,
        "complexity_metrics": complexity_metrics,
        "stated_vs_actual": stated_vs_actual,
        "ui_regions": ui_regions,
    }

    episode["evidence"] = evidence

    errors = validate_v2(episode)
    if errors:
        print(f"  Warning: episode failed v2 validation after evidence extraction ({len(errors)} error(s)):")
        for error in errors:
            print(f"    - {error}")

    with open(episode_json_path, "w", encoding="utf-8") as f:
        json.dump(episode, f, indent=2)

    return episode
