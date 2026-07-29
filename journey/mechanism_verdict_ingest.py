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

from attribute_agents.base import ATTRIBUTES
from config.settings import PROJECT_ROOT
from journey.schema_migration import load_episode, validate_mechanism_verdict, validate_v2
from llm.payload_builder import ROLES
from recorder.interactive_v2 import EPISODE_FILENAME


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
