"""Assembles the data a single-episode HTML report needs from a stored
episode (Layer 2): the screenshot filmstrip, evidence tables, and every
attribute verdict's evidence pointers resolved to a bounding box on the
screenshot they reference. No HTML is generated here -- report.py owns
rendering; this module is pure data assembly plus the file reads (masked
screenshots, computed_styles) an HTML renderer alone couldn't do.

Bounding-box resolution reads computed_styles_path (recorder/evidence_probe.py)
for the pointer's step_id and looks up the element whose `selector` field
matches the pointer's `selector` exactly -- the same selector strings
signals/visual_asymmetry.py already matched pairs on. bounding_box.x/y are
document-relative, matching a full-page screenshot's own pixel space
(see evidence_probe.py's comment) -- this assumes
config.capture.screenshot_full_page (the default), the only capture mode
exercised anywhere in this project.
"""

import base64
import json
import os
from typing import Dict, List, Optional

from PIL import Image

VERDICT_COLOR_PRIORITY = {"fires": 2, "unsure": 1}  # higher wins when boxes at the same spot disagree


def _read_bytes(path: str) -> Optional[bytes]:
    if not path or not os.path.isfile(path):
        return None
    with open(path, "rb") as f:
        return f.read()


def _read_json(path: str) -> Optional[List[Dict]]:
    if not path or not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _image_dimensions(image_bytes: bytes) -> Optional[Dict]:
    try:
        from io import BytesIO
        with Image.open(BytesIO(image_bytes)) as img:
            return {"width": img.width, "height": img.height}
    except Exception:
        return None


def _build_filmstrip(episode: Dict, episode_dir: str) -> List[Dict]:
    steps = sorted(episode.get("steps") or [], key=lambda s: s["step_id"])
    filmstrip = []
    for step in steps:
        masked = step.get("screenshot_masked_path")
        image_bytes = _read_bytes(os.path.join(episode_dir, masked)) if masked else None
        dimensions = _image_dimensions(image_bytes) if image_bytes else None
        action = step.get("action") or {}
        filmstrip.append({
            "step_id": step["step_id"],
            "screenshot_b64": base64.b64encode(image_bytes).decode("ascii") if image_bytes else None,
            "image_width": dimensions["width"] if dimensions else None,
            "image_height": dimensions["height"] if dimensions else None,
            "action_type": action.get("type"),
            "selector": action.get("selector"),
            "page_url_redacted": step.get("page_url_redacted"),
            "tab_id": step.get("tab_id"),
            "capture_error": step.get("capture_error"),
        })
    return filmstrip


def _computed_styles_by_step(episode: Dict, episode_dir: str) -> Dict[int, List[Dict]]:
    by_step = {}
    for step in episode.get("steps") or []:
        cs_path = step.get("computed_styles_path")
        elements = _read_json(os.path.join(episode_dir, cs_path)) if cs_path else None
        by_step[step["step_id"]] = elements or []
    return by_step


def _bounding_box_for(computed_styles_by_step: Dict[int, List[Dict]], step_id: Optional[int], selector: Optional[str]) -> Optional[Dict]:
    if step_id is None or not selector:
        return None
    for element in computed_styles_by_step.get(step_id, []):
        if element.get("selector") == selector:
            return element["bounding_box"]
    return None


def _resolve_pointers(result: Dict, computed_styles_by_step: Dict[int, List[Dict]]) -> List[Dict]:
    resolved = []
    for pointer in result["evidence_pointers"]:
        resolved.append({
            **pointer,
            "attribute": result["attribute"],
            "verdict": result["verdict"],
            "bounding_box": _bounding_box_for(computed_styles_by_step, pointer["step_id"], pointer["selector"]),
        })
    return resolved


def _resolve_regions(computed_output: Optional[Dict], computed_styles_by_step: Dict[int, List[Dict]]) -> List[Dict]:
    """Attaches a representative_step_id/representative_bounding_box to
    each region (computed_output.regions, already built by
    journey/episode_output_builder.py) so report_html.py can draw a
    thumbnail without re-deriving anything -- the first step in the
    region's own `steps` whose computed_styles has an element matching
    representative_element wins."""
    resolved = []
    for region in (computed_output or {}).get("regions") or []:
        selector = region.get("representative_element")
        step_id, bounding_box = None, None
        if selector:
            for sid in region["steps"]:
                match = next(
                    (el for el in computed_styles_by_step.get(sid, []) if el.get("selector") == selector), None
                )
                if match is not None:
                    step_id, bounding_box = sid, match["bounding_box"]
                    break
        resolved.append({**region, "representative_step_id": step_id, "representative_bounding_box": bounding_box})
    return resolved


def _boxes_by_step(attribute_sections: List[Dict]) -> Dict[int, List[Dict]]:
    """Groups resolved pointers with a real bounding_box by step_id, merging
    multiple pointers at the same (step_id, selector) into one overlay box
    with a combined label -- so overlapping asymmetry dimensions on the
    same element draw once, not stacked duplicates."""
    grouped: Dict[int, Dict[str, Dict]] = {}
    for section in attribute_sections:
        for pointer in section["resolved_pointers"]:
            if pointer["bounding_box"] is None or pointer["step_id"] is None:
                continue
            step_id = pointer["step_id"]
            key = pointer["selector"]
            grouped.setdefault(step_id, {})
            existing = grouped[step_id].get(key)
            label = f"{pointer['attribute']}: {pointer['signal']}"
            if existing is None:
                grouped[step_id][key] = {
                    "bounding_box": pointer["bounding_box"],
                    "verdict": pointer["verdict"],
                    "labels": [label],
                }
            else:
                existing["labels"].append(label)
                if VERDICT_COLOR_PRIORITY.get(pointer["verdict"], 0) > VERDICT_COLOR_PRIORITY.get(existing["verdict"], 0):
                    existing["verdict"] = pointer["verdict"]

    return {step_id: list(boxes.values()) for step_id, boxes in grouped.items()}


def build_report_data(episode: Dict, episode_dir: str) -> Dict:
    filmstrip = _build_filmstrip(episode, episode_dir)
    computed_styles_by_step = _computed_styles_by_step(episode, episode_dir)

    computed_output = (episode.get("mechanism_verdict") or {}).get("computed_output")
    # computed_output.verdicts is the authoritative, LLM-override-applied
    # list once build-output has run; before that (or if it never has),
    # fall back to the code agents' own raw episode.attributes.results so
    # the report still renders something.
    verdicts_source = computed_output["verdicts"] if computed_output else (episode.get("attributes") or {}).get("results") or []

    attribute_sections = []
    for result in verdicts_source:
        attribute_sections.append({
            **result,
            "resolved_pointers": _resolve_pointers(result, computed_styles_by_step),
        })

    boxes_by_step = _boxes_by_step(attribute_sections)
    for step in filmstrip:
        step["boxes"] = boxes_by_step.get(step["step_id"], [])

    return {
        "episode": episode.get("episode") or {},
        "outcome": episode.get("outcome") or {},
        "filmstrip": filmstrip,
        "evidence": episode.get("evidence") or {},
        "attribute_sections": attribute_sections,
        "mechanism_verdict_entries": (episode.get("mechanism_verdict") or {}).get("entries") or [],
        "overall": (computed_output or {}).get("overall"),
        "regions": _resolve_regions(computed_output, computed_styles_by_step),
    }
