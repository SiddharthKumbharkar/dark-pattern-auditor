"""Tests for schema/episode.v2.schema.json -- and the additive-only
composition (v2 reuses v1's $defs by pointer rather than redefining them)."""

import json
import os

from jsonschema import Draft202012Validator

from journey.schema_migration import validate_v1, validate_v2

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _v2_schema():
    schema_path = os.path.join(os.path.dirname(__file__), "..", "schema", "episode.v2.schema.json")
    with open(schema_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_fixture(name):
    with open(os.path.join(FIXTURES_DIR, name)) as f:
        return json.load(f)


def test_v2_schema_is_itself_valid():
    Draft202012Validator.check_schema(_v2_schema())


def test_v2_example_fixture_validates_cleanly():
    doc = _load_fixture("episode_v2_example.json")
    assert validate_v2(doc) == []


def test_v2_example_fixture_also_satisfies_v1_shape_for_its_legacy_fields():
    # Proves additivity structurally: the v1 fields inside a v2 document,
    # taken on their own, still satisfy the standalone v1 schema.
    doc = _load_fixture("episode_v2_example.json")
    v1_subset = {
        "audit_metadata": doc["audit_metadata"],
        "website_context": doc["website_context"],
        "journey_steps": doc["journey_steps"],
        "temporal_checks": doc["temporal_checks"],
        "disclosure_context": doc["disclosure_context"],
    }
    assert validate_v1(v1_subset) == []


def test_raw_v1_document_fails_v2_validation_without_migration():
    doc = _load_fixture("golden_journey_ccpa.json")
    errors = validate_v2(doc)
    assert "schema_version" in " ".join(errors)
    assert "episode" in " ".join(errors)
    assert "steps" in " ".join(errors)
    assert "outcome" in " ".join(errors)
    assert "privacy" in " ".join(errors)


def test_missing_new_field_in_episode_block_is_reported():
    doc = _load_fixture("episode_v2_example.json")
    del doc["episode"]["operator"]

    errors = validate_v2(doc)
    assert len(errors) == 1
    assert "episode" in errors[0]
    assert "operator" in errors[0]


def test_wrong_device_context_enum_value_is_reported():
    doc = _load_fixture("episode_v2_example.json")
    doc["episode"]["device_context"] = "tablet"

    errors = validate_v2(doc)
    assert len(errors) == 1
    assert "device_context" in errors[0]


def test_v1_nested_field_is_still_governed_by_v1s_own_rules():
    # A v2 document's journey_steps still goes through episode.v1's
    # JourneyStep $def -- corrupting a v1-owned nested field must still be
    # caught, proving v2 didn't quietly relax v1's own field rules.
    doc = _load_fixture("episode_v2_example.json")
    doc["journey_steps"][0]["user_action"]["action_type"] = 123

    errors = validate_v2(doc)
    assert len(errors) == 1
    assert "action_type" in errors[0]
