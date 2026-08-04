"""Ingests a manually-produced LLM response.json (Stage 2) back into a
stored episode's episode.mechanism_verdict block -- closing the loop
llm/payload_builder.py opened: build-payload writes prompt+evidence to
disk for a human to paste into an LLM by hand; ingest_response() reads
whatever came back and stores it, after two checks a human pasting JSON
by hand can easily get wrong:

  1. response.json must validate against the EXACT response_schema.json
     build-payload wrote for this (episode, role[, attribute]) -- read
     from disk, not regenerated, so validation matches what the human was
     actually shown, not whatever the current code happens to produce.
  2. every non-null step_id in the response's evidence_pointers (if it has
     any -- only --role attribute responses do today) must name a step
     that actually exists in this episode. Neither a human nor a model can
     be trusted not to invent one; nothing about JSON Schema validation
     alone would catch that.

One entry per (role, attribute) pair lives in
episode.mechanism_verdict.entries (attribute is null for triage/
coordinator, which assess the whole episode rather than one attribute).
Re-ingesting the same (role, attribute) REPLACES its entry rather than
appending a duplicate -- each ingest-response call represents the current
manual verdict for that role, not a growing log of every attempt.
"""

import json
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

from jsonschema import Draft202012Validator

from attribute_agents.base import ATTRIBUTES, build_region_map
from config.settings import PROJECT_ROOT
from journey.schema_migration import load_episode, validate_mechanism_verdict, validate_v2
from journey.verdict_output_builder import compute_region_groups, select_authoritative_verdicts
from llm.payload_builder import ROLES
from recorder.interactive_v2 import EPISODE_FILENAME
from signals.visual_claims import has_visual_claim, pointer_is_image_sourced


class IngestError(ValueError):
    """response.json failed schema or evidence-pointer validation, or the
    CLI arguments/on-disk payload didn't line up. Always carries the full
    list of specific, field-level messages in .errors -- these are shown
    to a human pasting JSON by hand, so every one of them must be
    actionable on its own, not just a generic "invalid" message."""

    def __init__(self, errors: List[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def _resolve_episode_json_path(path: str) -> str:
    if os.path.isdir(path):
        return os.path.join(path, EPISODE_FILENAME)
    return path


def _payload_dir(payload_root: str, episode_id: str, role: str, attribute: Optional[str]) -> str:
    if role == "attribute":
        return os.path.join(payload_root, episode_id, role, attribute)
    return os.path.join(payload_root, episode_id, role)


def _format_error(error) -> str:
    location = ".".join(str(p) for p in error.path) or "<root>"
    return f"{location}: {error.message}"


def validate_against_response_schema(response: Dict, response_schema: Dict) -> List[str]:
    validator = Draft202012Validator(response_schema)
    errors = sorted(validator.iter_errors(response), key=lambda e: [str(p) for p in e.path])
    return [_format_error(e) for e in errors]


def validate_evidence_pointers(response: Dict, valid_step_ids: set) -> List[str]:
    """Only meaningful once schema validation has already passed (so
    evidence_pointers, if present, is at least shaped correctly) -- this
    checks the one thing JSON Schema can't: that each non-null step_id
    actually names a step that was recorded in this episode. A response
    shape with no evidence_pointers field at all (coordinator, triage
    today) has nothing to check here."""
    pointers = response.get("evidence_pointers")
    if not isinstance(pointers, list):
        return []
    errors = []
    for i, pointer in enumerate(pointers):
        step_id = pointer.get("step_id") if isinstance(pointer, dict) else None
        if step_id is not None and step_id not in valid_step_ids:
            errors.append(
                f"evidence_pointers[{i}].step_id: {step_id} does not exist in this episode "
                f"(known step_ids: {sorted(valid_step_ids)}) -- fabricated pointer rejected."
            )
    return errors


def validate_evidence_pointer_regions(response: Dict, region_map: Dict) -> List[str]:
    """role=attribute only: each evidence_pointer's ui_region must match
    the region signals/ui_regions.py already assigned that exact
    (step_id, selector) -- a human or model claiming a DIFFERENT region
    than the extractor's own tag is exactly the "agents read the region,
    they do not invent it" rule, applied to a Stage-2 response the same
    way it's applied to a code agent's own evidence_pointers (see
    attribute_agents/base.py's enrich_evidence_pointers, the one other
    place this same lookup is used)."""
    pointers = response.get("evidence_pointers")
    if not isinstance(pointers, list):
        return []
    errors = []
    for i, pointer in enumerate(pointers):
        if not isinstance(pointer, dict):
            continue
        claimed = pointer.get("ui_region")
        expected = region_map.get((pointer.get("step_id"), pointer.get("selector")), "unclassified")
        if claimed != expected:
            errors.append(
                f"evidence_pointers[{i}].ui_region: {claimed!r} does not match the region already "
                f"assigned to (step_id={pointer.get('step_id')!r}, selector={pointer.get('selector')!r}) "
                f"by the evidence extractor ({expected!r}) -- regions are read from the extractor's "
                f"tagging, never invented."
            )
    return errors


def _screenshots_supplied(payload_dir: str) -> bool:
    manifest_path = os.path.join(payload_dir, "manifest.json")
    if not os.path.isfile(manifest_path):
        return False
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    return bool(manifest.get("screenshot_step_mapping"))


def validate_visual_claims_attribute(response: Dict, screenshots_supplied: bool) -> List[str]:
    """role=attribute: a `reasoning` that reads like it inspected a
    screenshot (see signals/visual_claims.py) must be grounded -- either a
    screenshot_visual_inspection-prefixed evidence_pointer, or an explicit
    visual_claim_unverified: true. If NO screenshot was even included in
    this payload (manifest.json's screenshot_step_mapping is empty), a
    visual claim is unambiguously fabricated -- rejected regardless of
    either flag, since there is nothing it could legitimately be
    grounded in."""
    reasoning = response.get("reasoning") or ""
    if not has_visual_claim(reasoning):
        return []

    if not screenshots_supplied:
        return [
            "reasoning: makes a visual claim (references what a screenshot shows) but this payload's "
            "manifest.json shows zero screenshots were included -- fabricated visual grounding, rejected."
        ]

    pointers = response.get("evidence_pointers") or []
    image_sourced = any(isinstance(p, dict) and pointer_is_image_sourced(p) for p in pointers)
    if image_sourced or response.get("visual_claim_unverified") is True:
        return []

    return [
        "reasoning: makes a visual claim but no evidence_pointers entry is image-sourced "
        "(signal prefixed \"screenshot_visual_inspection\") and visual_claim_unverified is not "
        "set to true -- do not silently trust an ungrounded visual claim."
    ]


def validate_visual_claims_coordinator(response: Dict) -> List[str]:
    """role=coordinator: pattern_combinations entries have no
    evidence_pointers of their own, so the only grounding available for a
    visual claim in `description` is the explicit flag -- no
    image-sourced-pointer escape hatch here (see
    llm/payload_builder.py's _coordinator_response_schema docstring)."""
    errors = []
    for i, combination in enumerate(response.get("pattern_combinations") or []):
        if not isinstance(combination, dict):
            continue
        description = combination.get("description") or ""
        if has_visual_claim(description) and combination.get("visual_claim_unverified") is not True:
            errors.append(
                f"pattern_combinations[{i}].description: makes a visual claim but "
                f"visual_claim_unverified is not set to true -- a pattern_combinations entry has no "
                f"evidence_pointers to ground it in any other way."
            )
    return errors


def validate_pattern_combinations_grounded(response: Dict, episode: Dict) -> List[str]:
    """role=coordinator: every (ui_region, attributes) pair must exactly
    match, or be a strict subset of, one of the region_groups
    journey/verdict_output_builder.py's compute_region_groups already
    computed for this episode -- the coordinator names/describes a
    combination, it does not get to invent which attributes co-occurred
    where."""
    combinations = response.get("pattern_combinations")
    if not isinstance(combinations, list) or not combinations:
        return []

    verdicts = select_authoritative_verdicts(episode)
    computed_groups = compute_region_groups(verdicts)["region_groups"]
    allowed_by_region: Dict[str, set] = {}
    for group in computed_groups:
        allowed_by_region.setdefault(group["ui_region"], set()).update(group["attributes"])

    errors = []
    for i, combination in enumerate(combinations):
        if not isinstance(combination, dict):
            continue
        region = combination.get("ui_region")
        attributes = set(combination.get("attributes") or [])
        allowed = allowed_by_region.get(region, set())
        invented = attributes - allowed
        if invented:
            errors.append(
                f"pattern_combinations[{i}]: attributes {sorted(invented)} were not computed as "
                f"co-occurring in ui_region {region!r} (region_groups only has {sorted(allowed)} there) "
                f"-- do not invent a combination beyond what evidence_summary.json's region_groups supplied."
            )
    return errors


def _infer_attribute(role: str, response: Dict, attribute_arg: Optional[str]) -> Optional[str]:
    if role != "attribute":
        if attribute_arg is not None:
            raise IngestError([f"--attribute is only valid with --role attribute, got --role {role!r}"])
        return None
    response_attribute = response.get("attribute") if isinstance(response, dict) else None
    if attribute_arg is not None and response_attribute is not None and attribute_arg != response_attribute:
        raise IngestError([
            f'--attribute {attribute_arg!r} does not match this response\'s own "attribute" field '
            f"({response_attribute!r}) -- wrong file, or pasted into the wrong folder."
        ])
    attribute = attribute_arg or response_attribute
    if attribute not in ATTRIBUTES:
        raise IngestError([
            f"could not determine which attribute this response is for (got {attribute!r}); pass "
            f"--attribute explicitly or make sure response.json has a valid \"attribute\" field."
        ])
    return attribute


def _load_json_file(path: str, what: str) -> Dict:
    if not os.path.isfile(path):
        raise IngestError([f"{what} not found: {path}"])
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as exc:
        raise IngestError([f"{path} is not valid JSON: {exc}"])


def _prompt_version_used(payload_dir: str) -> str:
    manifest_path = os.path.join(payload_dir, "manifest.json")
    if not os.path.isfile(manifest_path):
        raise IngestError([
            f"{manifest_path} not found -- this payload directory is incomplete or was never built "
            f"by build-payload."
        ])
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    prompt_version = manifest.get("prompt_version")
    if not prompt_version:
        raise IngestError([f"{manifest_path} has no prompt_version field -- integrity error."])
    return prompt_version


def ingest_response(
    episode_path: str,
    role: str,
    response_file: str,
    model_name: str,
    operator: str,
    attribute: Optional[str] = None,
    storage_dir: Optional[str] = None,
    payload_root: Optional[str] = None,
) -> Dict:
    """Idempotent per (role, attribute): re-ingesting the same combination
    replaces its prior entry in episode.mechanism_verdict.entries rather
    than accumulating a duplicate. Raises IngestError (with .errors, a
    list of specific field-level messages) on any validation failure --
    nothing is written to disk unless every check passes."""
    if role not in ROLES:
        raise IngestError([f"role must be one of {ROLES}, got {role!r}"])
    if not model_name:
        raise IngestError(["model_name is required (you must supply which model produced this response)."])
    if not operator:
        raise IngestError(["operator is required."])

    episode_json_path = _resolve_episode_json_path(episode_path)
    episode_dir = os.path.dirname(episode_json_path)
    if storage_dir is None:
        storage_dir = os.path.dirname(episode_dir)
    if payload_root is None:
        payload_root = os.path.join(PROJECT_ROOT, "payload")

    episode = load_episode(episode_json_path)
    episode_id = episode["episode"]["episode_id"]

    response = _load_json_file(response_file, "response file")
    if not isinstance(response, dict):
        raise IngestError(["response.json must contain a single JSON object, not a list/scalar."])

    resolved_attribute = _infer_attribute(role, response, attribute)

    payload_dir = _payload_dir(payload_root, episode_id, role, resolved_attribute)
    response_schema = _load_json_file(
        os.path.join(payload_dir, "response_schema.json"),
        f"response_schema.json for role={role!r}"
        + (f" attribute={resolved_attribute!r}" if resolved_attribute else "")
        + " (run build-payload first)",
    )

    schema_errors = validate_against_response_schema(response, response_schema)
    if schema_errors:
        raise IngestError(schema_errors)

    valid_step_ids = {step["step_id"] for step in (episode.get("steps") or [])}
    pointer_errors = validate_evidence_pointers(response, valid_step_ids)
    if pointer_errors:
        raise IngestError(pointer_errors)

    region_errors = validate_evidence_pointer_regions(response, build_region_map(episode))
    if region_errors:
        raise IngestError(region_errors)

    if role == "attribute":
        visual_errors = validate_visual_claims_attribute(response, _screenshots_supplied(payload_dir))
    elif role == "coordinator":
        visual_errors = validate_visual_claims_coordinator(response)
        visual_errors += validate_pattern_combinations_grounded(response, episode)
    else:
        visual_errors = []
    if visual_errors:
        for error in visual_errors:
            print(f"  Warning (rejected): {error}")
        raise IngestError(visual_errors)

    prompt_version = _prompt_version_used(payload_dir)

    entry = {
        "role": role,
        "attribute": resolved_attribute,
        "model_name": model_name,
        "prompt_version": prompt_version,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "operator": operator,
        "raw_response": response,
    }

    existing_entries = ((episode.get("mechanism_verdict") or {}).get("entries")) or []
    entries = [e for e in existing_entries if not (e["role"] == role and e["attribute"] == resolved_attribute)]
    entries.append(entry)
    mechanism_verdict = {"entries": entries}

    mv_errors = validate_mechanism_verdict(mechanism_verdict)
    if mv_errors:
        raise IngestError(mv_errors)

    episode["mechanism_verdict"] = mechanism_verdict

    errors = validate_v2(episode)
    if errors:
        raise IngestError(errors)

    with open(episode_json_path, "w", encoding="utf-8") as f:
        json.dump(episode, f, indent=2)

    return episode
