"""Assembles exactly what an LLM would receive for one (episode, role) --
and writes it to disk for MANUAL use. This module NEVER calls an API: no
`anthropic` import, no network I/O. It is the offline counterpart to
llm/judge.py -- everything a Stage 2 human-in-the-loop LLM pass would be
given is written under payload/<episode_id>/<role>/ instead of being sent
anywhere (Layer 4, per CLAUDE.md: "the only layer that calls an LLM" --
this module deliberately does not exercise that permission).

Three roles:
  triage      -- one fast, broad pass over ALL 7 attributes for one
                 episode, to tell a human auditor which attributes are
                 worth a full --role attribute deep-dive. All steps'
                 masked screenshots are included.
  attribute   -- a full single-attribute assessment (the "7-attribute"
                 prompt, prompts/attribute_prompt.v1.txt, parameterized
                 by --attribute). Includes only the evidence
                 ATTRIBUTE_EVIDENCE_MAP marks relevant to that attribute,
                 and only the screenshots its evidence_pointers
                 reference -- synthesized from the raw evidence's own
                 step_id fields, unioned with the matching entry (if any)
                 already in episode.attributes.results. Two exceptions,
                 covertness and information_hiding, additionally get
                 EVERY step's screenshot -- see _NEEDS_FULL_FLOW_SCREENSHOTS.
  coordinator -- synthesizes the 7 already-computed attribute results
                 (episode.attributes.results) into one overall
                 determination, shaped to paste into the
                 episode.mechanism_verdict placeholder block.

Every prompt is loaded from prompts/*.v1.txt by filename -- never inlined
here, matching CLAUDE.md's "never hardcode prompt text in
llm/prompt_builder.py" rule, extended to this module by the same logic.
Per-attribute definition prose lives in prompts/attribute_definitions.v1.json
for the same reason: it is prompt content, not code.

Idempotent: build_payload() always wipes and rewrites its target
directory, so re-running after new evidence/attributes were computed never
leaves stale files (a screenshot that's no longer relevant, an old
prompt_version) behind.
"""

import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from attribute_agents.base import ATTRIBUTES, build_region_map, enrich_evidence_pointers
from config.settings import PROJECT_ROOT, TOOL_VERSION
from config.ui_regions import REGION_IDS
from journey.schema_migration import load_episode
from journey.verdict_output_builder import compute_region_groups, select_authoritative_verdicts
from recorder.interactive_v2 import EPISODE_FILENAME

ROLES = ("triage", "attribute", "coordinator")

PROMPTS_DIR = os.path.join(PROJECT_ROOT, "prompts")
PROMPT_FILES = {
    "triage": "triage_prompt.v1.txt",
    "attribute": "attribute_prompt.v1.txt",
    "coordinator": "coordinator_prompt.v1.txt",
}
ATTRIBUTE_DEFINITIONS_FILE = "attribute_definitions.v1.json"

# Every entry per evidence key with a step_id-bearing shape, so screenshots
# can be derived directly from the raw evidence (see _derive_pointers).
ATTRIBUTE_EVIDENCE_MAP: Dict[str, Dict[str, List[str]]] = {
    "asymmetry": {"episode": ["visual_asymmetry"], "group": []},
    "covertness": {"episode": ["visual_asymmetry"], "group": []},
    "deception": {"episode": ["stated_vs_actual"], "group": ["claim_persistence", "timer_reset_detection"]},
    "information_hiding": {"episode": ["price_drift"], "group": []},
    "restriction": {"episode": ["friction_metrics", "path_deviation"], "group": ["paired_flow_comparison"]},
    "disparate_treatment": {"episode": [], "group": ["paired_flow_comparison"]},
    "complexity": {"episode": ["complexity_metrics"], "group": []},
}

MAX_ENTRIES_PER_LIST = 25  # keeps evidence_summary.json in the ~1-2k token range

# information_hiding is the only attribute that reads disclosure-tagged
# ui_regions entries (signals/ui_regions.py's opt-in data-disclosure pass)
# into its own evidence_summary.json -- see _disclosure_elements(). Scoped
# narrowly to this one attribute, not added to every payload, so covertness
# (already validated) sees exactly the evidence it saw on its validated
# run; nothing about this addition can change covertness's behavior.
_NEEDS_DISCLOSURE_ELEMENTS = ("information_hiding",)

# covertness and information_hiding have no dedicated structured signal
# that reliably LOCATES their evidence -- both are Stage-2-only precisely
# because no code signal CAN point at them (see their own module
# docstrings). ATTRIBUTE_EVIDENCE_MAP's mapped key still describes real,
# relevant evidence when it's non-empty (a genuinely asymmetric pair is
# still covertness-relevant; a genuine price_drift increase is still
# information_hiding-relevant) -- the problem is what it MISSES: a covert
# element that isn't part of an accept/reject pair (e.g. a buried,
# pre-checked opt-in) never appears via visual_asymmetry; a withheld term
# that isn't a numeric price at all (e.g. wording revealed late) never
# appears via price_drift. Both attributes fall back to every step's own
# screenshot in addition to whatever their mapped key found -- the same
# "show the whole flow" fallback _build_coordinator() already uses when
# nothing fired -- so narrow, possibly-incomplete evidence-key routing is
# never the ONLY grounding a human/LLM judge gets for these two.
_NEEDS_FULL_FLOW_SCREENSHOTS = ("covertness", "information_hiding")


class PayloadBuildError(ValueError):
    """A precondition for building this payload wasn't met (missing
    evidence/attributes, bad role/attribute combination, etc.) -- distinct
    from SchemaValidationError, which means the stored episode itself is
    malformed."""


# -- loading -----------------------------------------------------------


def _resolve_episode_json_path(path: str) -> str:
    if os.path.isdir(path):
        return os.path.join(path, EPISODE_FILENAME)
    return path


def load_group_evidence(episode: Dict, storage_dir: str) -> Optional[Dict]:
    group_evidence_path = (episode.get("episode") or {}).get("group_evidence_path")
    if not group_evidence_path:
        return None
    full_path = os.path.join(storage_dir, group_evidence_path)
    if not os.path.isfile(full_path):
        return None
    with open(full_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_attribute_definitions() -> Dict:
    with open(os.path.join(PROMPTS_DIR, ATTRIBUTE_DEFINITIONS_FILE), "r", encoding="utf-8") as f:
        return json.load(f)


def _load_prompt_template(role: str) -> str:
    with open(os.path.join(PROMPTS_DIR, PROMPT_FILES[role]), "r", encoding="utf-8") as f:
        return f.read()


# -- screenshots ---------------------------------------------------------


def _step_by_id(episode: Dict) -> Dict[int, Dict]:
    return {step["step_id"]: step for step in (episode.get("steps") or [])}


def _masked_screenshot_path(episode_dir: str, step: Dict) -> Optional[str]:
    """Only ever reads screenshot_masked_path, never screenshot_path (the
    unmasked one) -- "include masked screenshots only" is enforced by
    which field this function is willing to look at, not by a later
    filter. Returns None when the step legitimately has no screenshot
    (e.g. capture_error, or pre-masking-era v1 data) -- that is not an
    error. Asserts (rather than silently returning None) when a path IS
    recorded but the file it names is missing on disk: that combination
    is never legitimate, it means the episode folder is corrupted or was
    partially deleted.
    """
    masked = step.get("screenshot_masked_path")
    if not masked:
        return None
    full_path = os.path.join(episode_dir, masked)
    assert os.path.isfile(full_path), (
        f"step {step.get('step_id')}: screenshot_masked_path={masked!r} is set but the file is "
        f"missing on disk -- episode folder integrity error, not a legitimate absence."
    )
    return full_path


def _copy_screenshots(episode_dir: str, steps: List[Dict], screenshots_dir: str) -> List[Dict]:
    """Copies the masked screenshot for each step (skipping steps with none)
    into screenshots_dir, preserving the original filename. Returns the
    screenshot->step_id mapping, sorted by step_id."""
    os.makedirs(screenshots_dir, exist_ok=True)
    mapping = []
    for step in sorted(steps, key=lambda s: s["step_id"]):
        source = _masked_screenshot_path(episode_dir, step)
        if source is None:
            continue
        filename = os.path.basename(source)
        shutil.copyfile(source, os.path.join(screenshots_dir, filename))
        mapping.append({"filename": filename, "step_id": step["step_id"]})
    return mapping


# -- evidence pointer synthesis -------------------------------------------


def _pointers_from_visual_asymmetry(pairs: List[Dict]) -> List[Dict]:
    pointers = []
    for pair in pairs:
        pointers.append({"step_id": pair["step_id"], "selector": pair["positive_selector"], "signal": "visual_asymmetry"})
        pointers.append({"step_id": pair["step_id"], "selector": pair["negative_selector"], "signal": "visual_asymmetry"})
    return pointers


def _pointers_from_stated_vs_actual(entries: List[Dict]) -> List[Dict]:
    return [{"step_id": e["step_id"], "selector": None, "signal": "stated_vs_actual"} for e in entries]


def _pointers_from_price_drift(price_drift: Dict) -> List[Dict]:
    return [
        {"step_id": i["step_id"], "selector": None, "signal": "price_drift.increases"}
        for i in (price_drift.get("increases") or [])
    ]


def _pointers_from_path_deviation(entries: List[Dict]) -> List[Dict]:
    return [{"step_id": e["step_id"], "selector": None, "signal": "path_deviation"} for e in entries]


def _pointers_from_complexity_metrics(complexity_metrics: Dict) -> List[Dict]:
    pointers = [
        {"step_id": o["step_id"], "selector": None, "signal": "complexity_metrics.option_counts"}
        for o in (complexity_metrics.get("option_counts") or [])
    ]
    pointers.extend(
        {"step_id": c["step_id"], "selector": None, "signal": "complexity_metrics.copy_readability"}
        for c in (complexity_metrics.get("copy_readability") or [])
    )
    return pointers


def _derive_pointers(evidence_key: str, value) -> List[Dict]:
    """friction_metrics and the three group-level blocks (claim_persistence,
    timer_reset_detection, paired_flow_comparison) are intentionally absent
    here: they are aggregate/cross-episode signals with no single step_id
    of THIS episode to point a screenshot at."""
    if value is None:
        return []
    dispatch = {
        "visual_asymmetry": _pointers_from_visual_asymmetry,
        "stated_vs_actual": _pointers_from_stated_vs_actual,
        "price_drift": _pointers_from_price_drift,
        "path_deviation": _pointers_from_path_deviation,
        "complexity_metrics": _pointers_from_complexity_metrics,
    }
    fn = dispatch.get(evidence_key)
    return fn(value) if fn else []


def _dedup_pointers(pointers: List[Dict]) -> List[Dict]:
    seen = set()
    deduped = []
    for p in pointers:
        key = (p["step_id"], p["selector"], p["signal"])
        if key not in seen:
            seen.add(key)
            deduped.append(p)
    return deduped


def _disclosure_elements(episode: Dict) -> List[Dict]:
    """Every disclosure-tagged entry from episode.evidence.ui_regions --
    i.e. every tag carrying a "text" field (see signals/ui_regions.py's
    opt-in data-disclosure pass). Interactive-element tags never have
    "text", so this is a plain filter, not a re-classification.

    This is what actually closes the information_hiding grounding gap:
    build_region_map() already lets an agent's evidence_pointer validate
    against these (step_id, selector) pairs at ingest time, but nothing
    upstream of this function ever showed a model the pair to cite in the
    first place -- a real selector sitting only in region_map is invisible
    to whoever is reading evidence_summary.json. Surfacing {step_id,
    selector, region, text} here means a model that correctly reads
    "₹199 cancellation fee" in a screenshot has a genuine element to point
    at, instead of inventing one that then gets (correctly) rejected.
    """
    tags = (episode.get("evidence") or {}).get("ui_regions") or []
    return [dict(tag) for tag in tags if "text" in tag]


def _tagged_elements(episode: Dict, step_ids: List[int]) -> Tuple[List[Dict], int]:
    """The real (step_id, selector) -> region vocabulary for exactly the
    steps this payload shows the model (via screenshots) -- i.e. the same
    raw entries build_region_map() turns into a lookup dict, given here as
    a literal list so the model can be told to only use a NAMED region for
    a (step_id, selector) that actually appears here, and "unclassified"
    for anything that doesn't.

    Exists because a model reading a screenshot has always been able to
    correctly SEE an element without ever having a real tag for it -- most
    non-interactive, non-disclosure-tagged text on a real page has none --
    and would then guess a plausible-sounding region instead of writing
    "unclassified" as prompts/attribute_prompt.v1.txt's rule 4 already
    asked it to. journey/mechanism_verdict_ingest.py's
    coerce_untagged_evidence_pointer_regions() is the backstop for when
    that happens anyway; this is the prevention -- giving the model the
    actual ground truth instead of relying on it to remember an abstract
    rule.

    Disclosure-tagged entries (the "text"-carrying ones -- see
    signals/ui_regions.py) are NEVER subject to MAX_ENTRIES_PER_LIST
    capping here, only interactive-element entries are: a busy page can
    easily have 25+ nav/header/button tags before the flow even reaches a
    disclosure element several steps later, and dropping THAT entry would
    directly contradict relevant_evidence.disclosure_elements (built
    separately, uncapped, by _disclosure_elements()) reporting a real
    region for a (step_id, selector) that tagged_elements then claims not
    to know about -- exactly the kind of self-inflicted "not listed here,
    so 'unclassified'" mistake this whole mechanism exists to prevent.
    Returns (entries, truncated_count) -- truncated_count covers only the
    interactive subset, matching every other _cap_list() caller's shape.
    """
    step_id_set = set(step_ids)
    tags = [dict(tag) for tag in ((episode.get("evidence") or {}).get("ui_regions") or []) if tag["step_id"] in step_id_set]
    disclosure = [t for t in tags if "text" in t]
    interactive = [t for t in tags if "text" not in t]
    capped_interactive, truncated = _cap_list(interactive)
    combined = sorted(capped_interactive + disclosure, key=lambda t: t["step_id"])
    return combined, truncated


def _find_code_agent_result(episode: Dict, attribute: str) -> Optional[Dict]:
    results = ((episode.get("attributes") or {}).get("results")) or []
    matches = [r for r in results if r["attribute"] == attribute]
    for r in matches:
        if r["agent_type"] == "code":
            return r
    return matches[0] if matches else None


# -- compact evidence -----------------------------------------------------


def _cap_list(items: List) -> Tuple[List, int]:
    if len(items) <= MAX_ENTRIES_PER_LIST:
        return items, 0
    return items[:MAX_ENTRIES_PER_LIST], len(items) - MAX_ENTRIES_PER_LIST


def _compact_evidence_block(evidence: Dict) -> Dict:
    compact: Dict = {}
    for key in ("friction_metrics", "price_drift", "complexity_metrics"):
        if key in evidence:
            compact[key] = evidence[key]
    for key in ("visual_asymmetry", "claim_extraction", "path_deviation", "stated_vs_actual"):
        if key in evidence:
            capped, truncated = _cap_list(evidence[key])
            compact[key] = capped
            if truncated:
                compact[f"{key}_truncated_count"] = truncated
    return compact


def _compact_group_evidence(group_evidence: Optional[Dict]) -> Optional[Dict]:
    if group_evidence is None:
        return None
    compact: Dict = {}
    for key in ("claim_persistence", "timer_reset_detection", "paired_flow_comparison"):
        if key in group_evidence:
            capped, truncated = _cap_list(group_evidence[key])
            compact[key] = capped
            if truncated:
                compact[f"{key}_truncated_count"] = truncated
    return compact


def _episode_header(episode: Dict) -> Dict:
    meta = episode.get("episode") or {}
    return {
        "episode_id": meta.get("episode_id"),
        "site_id": meta.get("site_id"),
        "site_domain": meta.get("site_domain"),
        "sector": meta.get("sector"),
        "goal": meta.get("goal"),
        "revisit_index": meta.get("revisit_index"),
        "device_context": meta.get("device_context"),
    }


def _step_summary(step: Dict) -> Dict:
    action = step.get("action") or {}
    return {
        "step_id": step["step_id"],
        "action_type": action.get("type"),
        "selector": action.get("selector"),
        "page_url_redacted": step.get("page_url_redacted"),
        "tab_id": step.get("tab_id"),
    }


# -- role-specific evidence_summary / screenshot selection ----------------


def _build_triage(episode: Dict, group_evidence: Optional[Dict]) -> Tuple[Dict, List[int]]:
    steps = episode.get("steps") or []
    summary = {
        **_episode_header(episode),
        "outcome": episode.get("outcome") or {},
        "steps": [_step_summary(s) for s in sorted(steps, key=lambda s: s["step_id"])],
        "evidence": _compact_evidence_block(episode.get("evidence") or {}),
        "group_evidence": _compact_group_evidence(group_evidence),
    }
    step_ids = [s["step_id"] for s in steps]
    return summary, step_ids


def build_attribute_evidence_summary(episode: Dict, group_evidence: Optional[Dict], attribute: str) -> Tuple[Dict, List[int]]:
    evidence = episode.get("evidence") or {}
    evidence_map = ATTRIBUTE_EVIDENCE_MAP[attribute]

    relevant_evidence = {key: evidence[key] for key in evidence_map["episode"] if key in evidence}
    if attribute in _NEEDS_DISCLOSURE_ELEMENTS:
        disclosure_elements = _disclosure_elements(episode)
        if disclosure_elements:
            relevant_evidence["disclosure_elements"] = disclosure_elements
    relevant_group_evidence = {
        key: (group_evidence or {})[key] for key in evidence_map["group"] if group_evidence and key in group_evidence
    }

    pointers: List[Dict] = []
    for key, value in relevant_evidence.items():
        pointers.extend(_derive_pointers(key, value))

    code_result = _find_code_agent_result(episode, attribute)
    if code_result:
        pointers.extend(code_result["evidence_pointers"])
    region_map = build_region_map(episode)
    pointers = _dedup_pointers(enrich_evidence_pointers(pointers, region_map))

    step_ids = sorted({p["step_id"] for p in pointers if p["step_id"] is not None})
    if attribute in _NEEDS_FULL_FLOW_SCREENSHOTS:
        all_ids = {step["step_id"] for step in (episode.get("steps") or [])}
        step_ids = sorted(set(step_ids) | all_ids)

    tagged_elements, tagged_elements_truncated = _tagged_elements(episode, step_ids)

    summary = {
        **_episode_header(episode),
        "attribute": attribute,
        "relevant_evidence": relevant_evidence,
        "relevant_group_evidence": relevant_group_evidence,
        "code_agent_result": code_result,
        "evidence_pointers": pointers,
        "tagged_elements": tagged_elements,
    }
    if tagged_elements_truncated:
        summary["tagged_elements_truncated_count"] = tagged_elements_truncated
    return summary, step_ids


def _build_coordinator(episode: Dict) -> Tuple[Dict, List[int]]:
    results = ((episode.get("attributes") or {}).get("results")) or []
    # select_authoritative_verdicts prefers an already-ingested Stage-2
    # attribute-role verdict over the code agent's own result -- the
    # coordinator should group/name patterns off whichever verdict is
    # actually authoritative, same as journey/verdict_output_builder.py's
    # build_output() does for the final computed output.
    verdicts = select_authoritative_verdicts(episode)
    grouping = compute_region_groups(verdicts)
    summary = {
        **_episode_header(episode),
        "outcome": episode.get("outcome") or {},
        "attribute_results": results,
        "region_groups": grouping["region_groups"],
        "page_level_co_occurrence": grouping["page_level_co_occurrence"],
    }

    pointers: List[Dict] = []
    for result in results:
        if result["verdict"] in ("fires", "unsure"):
            pointers.extend(result["evidence_pointers"])
    step_ids = sorted({p["step_id"] for p in pointers if p["step_id"] is not None})

    if not step_ids:
        # No attribute fired/was unsure -- fall back to first+last step so
        # the coordinator still has some visual grounding for the flow.
        all_ids = sorted(step["step_id"] for step in (episode.get("steps") or []))
        if all_ids:
            step_ids = sorted({all_ids[0], all_ids[-1]})

    return summary, step_ids


# -- prompt rendering -------------------------------------------------


def _render(template: str, mapping: Dict[str, str]) -> str:
    text = template
    for key, value in mapping.items():
        text = text.replace(f"<<{key}>>", value)
    if "<<" in text:
        leftover = text[text.index("<<"): text.index("<<") + 40]
        raise PayloadBuildError(f"prompt template has an unfilled placeholder near: {leftover!r}")
    return text


def _screenshot_list_text(mapping: List[Dict], step_by_id: Dict[int, Dict]) -> str:
    if not mapping:
        return "  (no screenshots included for this payload)"
    lines = []
    for entry in mapping:
        step = step_by_id.get(entry["step_id"], {})
        action = step.get("action") or {}
        target = action.get("selector") or step.get("page_url_redacted") or ""
        lines.append(f"  - {entry['filename']}  (step {entry['step_id']}: {action.get('type')} {target})".rstrip())
    return "\n".join(lines)


def _outcome_summary_text(outcome: Dict) -> str:
    return (
        f"goal_achieved={outcome.get('goal_achieved')}, "
        f"steps_to_complete={outcome.get('steps_to_complete')}, "
        f"abandoned_reason={outcome.get('abandoned_reason')!r}"
    )


# -- response schemas -------------------------------------------------


def _evidence_pointer_schema() -> Dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["step_id", "selector", "ui_region", "signal"],
        "properties": {
            "step_id": {"type": ["integer", "null"]},
            "selector": {"type": ["string", "null"]},
            "ui_region": {
                "enum": list(REGION_IDS),
                "description": (
                    "Copy this from the matching pointer's ui_region already shown to you in "
                    "evidence_summary.json -- never invent one. If you're pointing at something not "
                    "already tagged there, use \"unclassified\"."
                ),
            },
            "signal": {
                "type": "string",
                "minLength": 1,
                "description": (
                    "Which measurement/observation this points at. If this specific claim rests on "
                    "something you saw in an attached screenshot (not a measured field in "
                    "evidence_summary.json), prefix it \"screenshot_visual_inspection\" -- see "
                    "response_schema.json's top-level note on visual claims."
                ),
            },
        },
    }


def _attribute_response_schema(attribute: str) -> Dict:
    """Mirrors schema/episode.v2.schema.json's #/$defs/AttributeResult, but
    only the 6 keys a JUDGEMENT actually produces (attribute, verdict,
    severity, confidence, evidence_pointers, reasoning) -- agent_version
    and agent_type are tool metadata attached mechanically afterward (see
    INSTRUCTIONS.txt), not something to ask a model to invent, mirroring
    exactly what attribute_agents/*.py's assess() functions return before
    attribute_agents/base.py.run_agent() fills those two in."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": f"AttributeResult judgement for '{attribute}' (Stage 2, LLM)",
        "description": (
            "Visual claims: if `reasoning` describes what a screenshot shows (color, legibility, "
            "layout, contrast, etc.), you MUST either (a) include at least one evidence_pointers "
            "entry whose signal is prefixed \"screenshot_visual_inspection\", or (b) set "
            "visual_claim_unverified: true. A response with a visual claim and neither is rejected "
            "at ingest -- see journey/mechanism_verdict_ingest.py."
        ),
        "type": "object",
        "additionalProperties": False,
        "required": ["attribute", "verdict", "severity", "confidence", "evidence_pointers", "reasoning"],
        "properties": {
            "attribute": {"const": attribute},
            "verdict": {"enum": ["fires", "no", "unsure", "not_assessable"]},
            "severity": {"anyOf": [{"type": "integer", "minimum": 1, "maximum": 5}, {"type": "null"}]},
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "evidence_pointers": {"type": "array", "items": _evidence_pointer_schema()},
            "reasoning": {"type": "string", "minLength": 1},
            "visual_claim_unverified": {
                "type": "boolean",
                "description": "Optional. Set true if reasoning makes a visual claim you cannot ground in an image-sourced evidence_pointers entry.",
            },
        },
    }


def _triage_response_schema() -> Dict:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Triage response",
        "type": "object",
        "additionalProperties": False,
        "required": ["episode_id", "attribute_triage"],
        "properties": {
            "episode_id": {"type": "string"},
            "attribute_triage": {
                "type": "array",
                "minItems": len(ATTRIBUTES),
                "maxItems": len(ATTRIBUTES),
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["attribute", "preliminary_read", "worth_deep_dive", "notes"],
                    "properties": {
                        "attribute": {"enum": list(ATTRIBUTES)},
                        "preliminary_read": {"enum": ["fires", "no", "unsure", "not_assessable"]},
                        "worth_deep_dive": {"type": "boolean"},
                        "notes": {"type": "string", "minLength": 1},
                    },
                },
            },
        },
    }


def _coordinator_response_schema() -> Dict:
    """overall_verdict/top_findings/human_review_recommended/summary are
    deliberately NOT part of this schema -- those are computed
    mechanically from episode.attributes.results by
    journey/verdict_output_builder.py::build_output() (the build-output
    CLI), never hand-authored, so they can never drift into a thinner
    shape than the verdicts they're derived from (see the task's Issue 1).
    What's left for the coordinator to actually judge is the one genuinely
    interpretive question a fixed rule can't answer: given attributes that
    co-occur in the SAME ui_region (evidence_summary.json's region_groups,
    already computed and given to you), what named pattern does that
    combination amount to?
    """
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Coordinator response (pastes into episode.mechanism_verdict)",
        "description": (
            "Ground every pattern_combinations entry in evidence_summary.json's region_groups -- "
            "its ui_region and attributes must exactly match (or be a subset of) one region_groups "
            "entry. Do not invent a region or an attribute that isn't already listed there; do not "
            "combine attributes from page_level_co_occurrence into a named pattern -- page-level-only "
            "co-occurrence is a weak signal, not a combination. A pattern_combinations entry has no "
            "evidence_pointers of its own, so if `description` makes a visual claim you MUST set "
            "visual_claim_unverified: true -- there is no image-sourced-pointer escape hatch here "
            "the way there is for the attribute prompt."
        ),
        "type": "object",
        "additionalProperties": False,
        "required": ["pattern_combinations"],
        "properties": {
            "pattern_combinations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["ui_region", "attributes", "pattern_name", "description"],
                    "properties": {
                        "ui_region": {"enum": list(REGION_IDS)},
                        "attributes": {
                            "type": "array",
                            "minItems": 2,
                            "items": {"enum": list(ATTRIBUTES)},
                        },
                        "pattern_name": {"type": "string", "minLength": 1},
                        "description": {"type": "string", "minLength": 1},
                        "visual_claim_unverified": {"type": "boolean"},
                    },
                },
            },
        },
    }


# -- token estimate / checksum / instructions -----------------------------


def _token_estimate(text_blobs: List[str], screenshot_count: int) -> Dict:
    chars = sum(len(t) for t in text_blobs)
    return {
        "text_chars": chars,
        "estimated_tokens": round(chars / 4),
        "screenshot_count": screenshot_count,
        "method": (
            "chars/4 heuristic over prompt.txt + evidence_summary.json + response_schema.json. "
            "Approximate, model-agnostic; excludes per-model image-token cost for the "
            "screenshot_count attachments -- that varies by vendor/resolution and isn't "
            "computable without calling an API, which this tool never does."
        ),
    }


def _checksum(file_bytes: Dict[str, bytes]) -> Dict:
    digests = {name: hashlib.sha256(data).hexdigest() for name, data in file_bytes.items()}
    combined_input = "\n".join(f"{name}:{digest}" for name, digest in sorted(digests.items())).encode("utf-8")
    return {
        "algorithm": "sha256",
        "combined": hashlib.sha256(combined_input).hexdigest(),
        "files": digests,
    }


_INSTRUCTIONS_TAIL = {
    "triage": (
        "This is a fast, broad pass, not a final verdict. Use attribute_triage entries with "
        "worth_deep_dive: true to decide which attributes deserve a follow-up run of:\n"
        "  python3 build_payload.py <episode_id> --role attribute --attribute <name>"
    ),
    "attribute": (
        "To fold this response into the stored episode, run:\n"
        "  python3 ingest_response.py <episode_id> --role attribute --file response.json "
        '--model "<model name>" --operator "<your name>"\n'
        "This validates the response against response_schema.json, rejects any evidence_pointer "
        "whose step_id doesn't actually exist in this episode, and writes it into "
        "episode.mechanism_verdict.entries alongside model_name/prompt_version/ingested_at/operator. "
        "Afterward, run:\n"
        "  python3 compare_verdicts.py <episode_id>\n"
        "to see this LLM verdict next to the code agent's own verdict for this attribute."
    ),
    "coordinator": (
        "To fold this response into the stored episode, run:\n"
        "  python3 ingest_response.py <episode_id> --role coordinator --file response.json "
        '--model "<model name>" --operator "<your name>"\n'
        "This validates the response against response_schema.json and writes it into "
        "episode.mechanism_verdict.entries alongside model_name/prompt_version/ingested_at/operator. "
        "Then run:\n"
        "  python3 build_output.py <episode_id>\n"
        "to compute overall_verdict/coverage/top_findings/summary -- those are generated from "
        "episode.attributes.results wholesale, not part of this response, so build-output must run "
        "(and re-run after any later re-ingest) for them to reflect this pattern_combinations pass."
    ),
}


def _instructions_text(role: str, attribute: Optional[str], prompt_version: str, built_at: str) -> str:
    tail = _INSTRUCTIONS_TAIL[role]
    attribute_line = f"Attribute:  {attribute}\n" if attribute else ""
    return f"""HOW TO USE THIS PAYLOAD
========================
Role:       {role}
{attribute_line}
1. Open prompt.txt and copy its full contents into your LLM chat as the
   system/first message.
2. Attach evidence_summary.json (as a file, or paste its contents) as the
   evidence payload.
3. Attach every image under screenshots/ -- their filenames match the
   step_id mapping listed in prompt.txt and in manifest.json's
   "screenshot_step_mapping".
4. response_schema.json documents the EXACT JSON shape the model's reply
   must match. Ask the model to return ONLY that JSON (prompt.txt already
   says this too, but repeat it if your interface strips instructions).
5. When you have the model's response, save it as response.json in THIS
   SAME DIRECTORY.

{tail}

This payload was assembled entirely offline (no API was called to build
it) -- prompt_version={prompt_version}, built_at={built_at}.
"""


# -- entry point -----------------------------------------------------


def build_payload(
    episode_path: str,
    role: str,
    attribute: Optional[str] = None,
    storage_dir: Optional[str] = None,
    payload_root: Optional[str] = None,
) -> Dict:
    if role not in ROLES:
        raise PayloadBuildError(f"role must be one of {ROLES}, got {role!r}")
    if role == "attribute":
        if attribute not in ATTRIBUTES:
            raise PayloadBuildError(f"--attribute must be one of {ATTRIBUTES}, got {attribute!r}")
    elif attribute is not None:
        raise PayloadBuildError(f"--attribute is only valid with --role attribute, got --role {role!r}")

    episode_json_path = _resolve_episode_json_path(episode_path)
    episode_dir = os.path.dirname(episode_json_path)
    if storage_dir is None:
        storage_dir = os.path.dirname(episode_dir)
    if payload_root is None:
        payload_root = os.path.join(PROJECT_ROOT, "payload")

    episode = load_episode(episode_json_path)
    episode_id = episode["episode"]["episode_id"]

    if not (episode.get("evidence") or {}).get("extractor_version"):
        raise PayloadBuildError(
            f"episode {episode_id!r} has no evidence yet -- run extract-evidence before build-payload."
        )
    if role == "coordinator" and not ((episode.get("attributes") or {}).get("results")):
        raise PayloadBuildError(
            f"episode {episode_id!r} has no attribute results yet -- run run-attributes before "
            f"build-payload --role coordinator."
        )

    group_evidence = load_group_evidence(episode, storage_dir)
    step_by_id = _step_by_id(episode)

    if role == "triage":
        evidence_summary, step_ids = _build_triage(episode, group_evidence)
    elif role == "attribute":
        evidence_summary, step_ids = build_attribute_evidence_summary(episode, group_evidence, attribute)
    else:
        evidence_summary, step_ids = _build_coordinator(episode)

    payload_dir = (
        os.path.join(payload_root, episode_id, role, attribute)
        if role == "attribute"
        else os.path.join(payload_root, episode_id, role)
    )
    shutil.rmtree(payload_dir, ignore_errors=True)
    os.makedirs(payload_dir, exist_ok=True)

    selected_steps = [step_by_id[sid] for sid in step_ids if sid in step_by_id]
    screenshot_mapping = _copy_screenshots(episode_dir, selected_steps, os.path.join(payload_dir, "screenshots"))

    if role == "attribute":
        response_schema = _attribute_response_schema(attribute)
    elif role == "triage":
        response_schema = _triage_response_schema()
    else:
        response_schema = _coordinator_response_schema()

    prompt_version = os.path.splitext(PROMPT_FILES[role])[0]
    template = _load_prompt_template(role)
    header = _episode_header(episode)
    placeholders = {
        "EPISODE_ID": str(header["episode_id"]),
        "SITE_DOMAIN": str(header["site_domain"]),
        "SECTOR": str(header["sector"]),
        "GOAL": str(header["goal"]),
        "REVISIT_INDEX": str(header["revisit_index"]),
        "DEVICE_CONTEXT": str(header["device_context"]),
        "SCREENSHOT_LIST": _screenshot_list_text(screenshot_mapping, step_by_id),
        "RESPONSE_SCHEMA_JSON": json.dumps(response_schema, indent=2),
    }
    if role == "attribute":
        definitions = _load_attribute_definitions()[attribute]
        placeholders["ATTRIBUTE_NAME"] = attribute
        placeholders["ATTRIBUTE_DEFINITION"] = definitions["definition"]
        placeholders["CODE_AGENT_NOTE"] = definitions["code_agent_note"]
    if role == "coordinator":
        placeholders["OUTCOME_SUMMARY"] = _outcome_summary_text(episode.get("outcome") or {})

    prompt_text = _render(template, placeholders)
    evidence_summary_text = json.dumps(evidence_summary, indent=2)
    response_schema_text = json.dumps(response_schema, indent=2)
    built_at = datetime.now(timezone.utc).isoformat()
    instructions_text = _instructions_text(role, attribute, prompt_version, built_at)

    file_bytes = {
        "prompt.txt": prompt_text.encode("utf-8"),
        "evidence_summary.json": evidence_summary_text.encode("utf-8"),
        "response_schema.json": response_schema_text.encode("utf-8"),
    }
    for entry in screenshot_mapping:
        with open(os.path.join(payload_dir, "screenshots", entry["filename"]), "rb") as f:
            file_bytes[f"screenshots/{entry['filename']}"] = f.read()

    with open(os.path.join(payload_dir, "prompt.txt"), "w", encoding="utf-8") as f:
        f.write(prompt_text)
    with open(os.path.join(payload_dir, "evidence_summary.json"), "w", encoding="utf-8") as f:
        f.write(evidence_summary_text)
    with open(os.path.join(payload_dir, "response_schema.json"), "w", encoding="utf-8") as f:
        f.write(response_schema_text)
    with open(os.path.join(payload_dir, "INSTRUCTIONS.txt"), "w", encoding="utf-8") as f:
        f.write(instructions_text)

    token_estimate = _token_estimate(
        [prompt_text, evidence_summary_text, response_schema_text], len(screenshot_mapping)
    )
    checksum = _checksum(file_bytes)

    manifest = {
        "episode_id": episode_id,
        "role": role,
        "attribute": attribute,
        "prompt_version": prompt_version,
        "prompt_file": os.path.join("prompts", PROMPT_FILES[role]),
        "built_at": built_at,
        "tool_version": TOOL_VERSION,
        "metadata": {
            **header,
            "paired_episode_id": (episode.get("episode") or {}).get("paired_episode_id"),
            "schema_version": episode.get("schema_version"),
        },
        "screenshot_step_mapping": screenshot_mapping,
        "token_estimate": token_estimate,
        "checksum": checksum,
        "payload_dir": payload_dir,
    }
    with open(os.path.join(payload_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    return manifest
