"""v1 <-> v2 episode schema validation and the v1-to-v2 migration shim (Layer 2).

episode.v1.schema.json and episode.v2.schema.json (schema/) are the source
of truth for shape; this module is the only place that (a) resolves their
cross-file $refs into validators and (b) knows how to upgrade a v1 document
into a v2-conformant one. See CLAUDE.md and the v2 schema's own
description for the additive-only contract this preserves.
"""

import json
import os
from typing import Dict, List, Optional, Tuple

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from config.settings import PROJECT_ROOT
from journey.manifest import MANIFEST_FILENAME
from journey.privacy import find_privacy_violations
from signals.price import build_price_timeline

SCHEMA_DIR = os.path.join(PROJECT_ROOT, "schema")
V1_SCHEMA_PATH = os.path.join(SCHEMA_DIR, "episode.v1.schema.json")
V2_SCHEMA_PATH = os.path.join(SCHEMA_DIR, "episode.v2.schema.json")
GROUP_EVIDENCE_SCHEMA_PATH = os.path.join(SCHEMA_DIR, "group_evidence.v1.schema.json")
MECHANISM_VERDICT_SCHEMA_PATH = os.path.join(SCHEMA_DIR, "mechanism_verdict.v1.schema.json")

CURRENT_SCHEMA_VERSION = 2

# v1's fixed viewport (recorder/browser.py:VIEWPORT) applied to every step
# of every v1 recording -- a genuine fact about how v1 data was captured,
# not a guess, so migrated steps can carry it accurately.
_V1_VIEWPORT = {"width": 1440, "height": 900}


class SchemaValidationError(ValueError):
    def __init__(self, errors: List[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def _load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _build_registry() -> Tuple[Registry, dict, dict]:
    v1_schema = _load_json(V1_SCHEMA_PATH)
    v2_schema = _load_json(V2_SCHEMA_PATH)
    registry = Registry().with_resources(
        [
            (v1_schema["$id"], Resource.from_contents(v1_schema)),
            (v2_schema["$id"], Resource.from_contents(v2_schema)),
        ]
    )
    return registry, v1_schema, v2_schema


def _format_error(error) -> str:
    location = ".".join(str(p) for p in error.path) or "<root>"
    return f"{location}: {error.message}"


def _sorted_errors(validator: Draft202012Validator, doc: dict) -> List[str]:
    errors = sorted(validator.iter_errors(doc), key=lambda e: [str(p) for p in e.path])
    return [_format_error(e) for e in errors]


def validate_v1(doc: dict) -> List[str]:
    """Returns a list of human-readable field-level errors (empty if valid)."""
    registry, v1_schema, _ = _build_registry()
    validator = Draft202012Validator(v1_schema, registry=registry)
    return _sorted_errors(validator, doc)


def validate_v2(doc: dict) -> List[str]:
    """Returns a list of human-readable field-level errors (empty if valid)."""
    registry, _, v2_schema = _build_registry()
    validator = Draft202012Validator(v2_schema, registry=registry)
    return _sorted_errors(validator, doc)


def validate_group_evidence(doc: dict) -> List[str]:
    """Returns a list of human-readable field-level errors (empty if valid).
    group_evidence.json is a standalone document (no cross-file $refs into
    episode.v1/v2), so this doesn't need the shared registry."""
    schema = _load_json(GROUP_EVIDENCE_SCHEMA_PATH)
    validator = Draft202012Validator(schema)
    return _sorted_errors(validator, doc)


def validate_mechanism_verdict(doc: dict) -> List[str]:
    """Returns a list of human-readable field-level errors (empty if valid).
    Validates the {entries:[...]} shape journey/mechanism_verdict_ingest.py
    writes into episode.mechanism_verdict -- standalone (no cross-file
    $refs), same reasoning as validate_group_evidence. episode.v2's own
    mechanism_verdict field stays freeform (additionalProperties: true) so
    this stricter check never breaks a pre-Phase-4 episode's {} placeholder;
    it is only ever run against the entries dict ingest-response is about
    to write, not against every episode's mechanism_verdict on load."""
    schema = _load_json(MECHANISM_VERDICT_SCHEMA_PATH)
    validator = Draft202012Validator(schema)
    return _sorted_errors(validator, doc)


def validate_computed_output(doc: dict) -> List[str]:
    """Returns a list of human-readable field-level errors (empty if
    valid). Validates just the {builder_version, verdicts, coverage, ...}
    shape journey/verdict_output_builder.py produces and build_output.py
    writes into episode.mechanism_verdict.computed_output, against the
    #/$defs/ComputedOutput def inside mechanism_verdict.v1.schema.json --
    same file as validate_mechanism_verdict, different sub-schema, since
    computed_output is optional there and ingest-response never writes it."""
    schema = _load_json(MECHANISM_VERDICT_SCHEMA_PATH)
    computed_output_schema = {**schema["$defs"]["ComputedOutput"], "$defs": schema["$defs"]}
    validator = Draft202012Validator(computed_output_schema)
    return _sorted_errors(validator, doc)


def _operator_from_sibling_manifest(episode_path: str) -> Optional[str]:
    manifest_path = os.path.join(os.path.dirname(episode_path), MANIFEST_FILENAME)
    if not os.path.isfile(manifest_path):
        return None
    try:
        manifest = _load_json(manifest_path)
    except (OSError, json.JSONDecodeError):
        return None
    return manifest.get("operator")


def _derive_episode_block(v1_doc: Dict, operator: Optional[str]) -> Dict:
    audit_metadata = v1_doc.get("audit_metadata") or {}
    website_context = v1_doc.get("website_context") or {}
    target_domain = audit_metadata.get("target_domain") or ""
    return {
        "episode_id": audit_metadata.get("audit_id") or "",
        # v1 has no separate site-identity concept; target_domain is the
        # only site-identifying value it ever recorded.
        "site_id": target_domain,
        "site_domain": target_domain,
        "sector": website_context.get("industry") or "unknown",
        # v1 never recorded which goal (if any) an episode pursued --
        # null rather than a fabricated guess.
        "goal": None,
        # v1 never revisited within a single recorded episode.
        "revisit_index": 0,
        # recorder/browser.py's VIEWPORT is fixed desktop-sized for every
        # v1 recording -- a fact, not a guess.
        "device_context": "desktop",
        "locale": None,
        "paired_episode_id": None,
        "collection_mode": "manual",
        "operator": operator or "unknown",
        # A group-evidence run has never happened for this episode --
        # migrating from v1 doesn't create or join any group.
        "group_evidence_path": None,
    }


def _derive_steps_block(v1_doc: Dict) -> List[Dict]:
    steps = []
    for step in v1_doc.get("journey_steps") or []:
        user_action = step.get("user_action") or {}
        state_capture = step.get("state_capture") or {}
        screenshot_id = state_capture.get("screenshot_id") or ""
        dom_id = state_capture.get("dom_snapshot_id") or ""
        steps.append(
            {
                "step_id": step.get("step_id"),
                "timestamp": step.get("timestamp"),
                "action": {
                    "type": user_action.get("action_type") or "",
                    # v1's click listener never captured a CSS selector or
                    # a bounding box (see recorder/browser.py's
                    # _CLICK_LISTENER_JS) -- null, not a guess.
                    "selector": None,
                    "bounding_box": None,
                    "input_redacted": user_action.get("input_value_masked") is not None,
                },
                # v1 never masked anything before persisting it -- these
                # *_path fields are genuinely unmasked artifacts, and the
                # corresponding *_masked_path fields are null because no
                # masked version was ever produced for this data.
                "screenshot_path": f"screenshots/{screenshot_id}" if screenshot_id else None,
                "screenshot_masked_path": None,
                "dom_snapshot_path": f"dom/{dom_id}" if dom_id else None,
                "dom_snapshot_masked_path": None,
                # v1 never captured network traffic (capture.capture_network
                # has no producer yet -- see config.yaml).
                "network_events": [],
                # v1 never redacted URLs before persisting them; this is a
                # known, disclosed gap for migrated data, not a claim that
                # redaction happened.
                "page_url_redacted": step.get("url") or "",
                "viewport": dict(_V1_VIEWPORT),
                # v1's capture_step() either fully succeeds or the whole
                # step is silently dropped by the caller on exception (see
                # recorder/browser.py:_poll_for_navigation) -- there is no
                # partial-failure representation to migrate, so every
                # migrated step is a clean capture.
                "capture_error": None,
                # v1 never tracked multiple tabs/popups -- every step came
                # from the single page the recorder drove.
                "tab_id": "main",
                # v1 never captured computed CSS/geometry -- no producer
                # existed until recorder/evidence_probe.py.
                "computed_styles_path": None,
            }
        )
    return steps


def _derive_outcome_block(v1_doc: Dict) -> Dict:
    journey_steps = v1_doc.get("journey_steps") or []
    timeline = build_price_timeline(journey_steps)
    all_prices = [price for entry in timeline for price in entry.get("prices", [])]
    return {
        # v1 never assessed goal completion -- null, not a fabricated
        # true/false.
        "goal_achieved": None,
        "abandoned_reason": None,
        "steps_to_complete": len(journey_steps),
        "first_price_shown": all_prices[0] if all_prices else None,
        "final_price_shown": all_prices[-1] if all_prices else None,
        "operator_notes": "",
    }


def _derive_privacy_block(v1_doc: Dict) -> Dict:
    violations: List[str] = []
    for step in v1_doc.get("journey_steps") or []:
        violations.extend(find_privacy_violations(step.get("user_action") or {}))
    return {
        # No masking stage ran over v1 data -- null, not a fake version.
        "masker_version": None,
        "redactions_applied": [],
        # This IS a real check: every v1 step's user_action is run through
        # the same journey/privacy.py gate JourneyBuilder uses today.
        "validation_passed": len(violations) == 0,
    }


def migrate_v1_to_v2(v1_doc: Dict, *, operator: Optional[str] = None) -> Dict:
    """Upgrades a v1 episode dict to v2. Every v1 field is carried through
    unchanged (name, type, meaning); only new top-level keys are added."""
    v2_doc = dict(v1_doc)
    v2_doc["schema_version"] = 2
    v2_doc["episode"] = _derive_episode_block(v1_doc, operator)
    v2_doc["steps"] = _derive_steps_block(v1_doc)
    v2_doc["outcome"] = _derive_outcome_block(v1_doc)
    v2_doc["privacy"] = _derive_privacy_block(v1_doc)
    v2_doc["evidence"] = {}
    v2_doc["attributes"] = {}
    v2_doc["ccpa_verdict"] = {}
    v2_doc["mechanism_verdict"] = {}
    return v2_doc


def load_episode(path: str) -> Dict:
    """The v2 loader. Reads any episode file (v1 or v2) and returns a
    validated v2 document -- migrating in memory if the file on disk is
    still v1. Raises SchemaValidationError if the result doesn't validate.
    """
    doc = _load_json(path)
    version = doc.get("schema_version", 1)

    if version == 1:
        operator = _operator_from_sibling_manifest(path)
        doc = migrate_v1_to_v2(doc, operator=operator)
    elif version != CURRENT_SCHEMA_VERSION:
        raise SchemaValidationError([f"<root>: unsupported schema_version {version!r}"])

    errors = validate_v2(doc)
    if errors:
        raise SchemaValidationError(errors)
    return doc
