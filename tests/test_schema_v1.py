"""Tests for schema/episode.v1.schema.json."""

import json
import os

from jsonschema import Draft202012Validator

from journey.schema_migration import validate_v1

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _v1_schema():
    schema_path = os.path.join(os.path.dirname(__file__), "..", "schema", "episode.v1.schema.json")
    with open(schema_path, "r", encoding="utf-8") as f:
        return json.load(f)


def test_v1_schema_is_itself_valid():
    Draft202012Validator.check_schema(_v1_schema())


def test_golden_fixture_validates_cleanly():
    with open(os.path.join(FIXTURES_DIR, "golden_journey_ccpa.json")) as f:
        doc = json.load(f)
    assert validate_v1(doc) == []


def test_missing_required_field_is_reported():
    with open(os.path.join(FIXTURES_DIR, "golden_journey_ccpa.json")) as f:
        doc = json.load(f)
    del doc["journey_steps"][0]["page_title"]

    errors = validate_v1(doc)
    assert len(errors) == 1
    assert "journey_steps.0" in errors[0]
    assert "page_title" in errors[0]


def test_wrong_type_is_reported():
    with open(os.path.join(FIXTURES_DIR, "golden_journey_ccpa.json")) as f:
        doc = json.load(f)
    doc["journey_steps"][0]["user_action"]["action_type"] = 123

    errors = validate_v1(doc)
    assert len(errors) == 1
    assert "action_type" in errors[0]


def test_unknown_top_level_field_is_rejected():
    with open(os.path.join(FIXTURES_DIR, "golden_journey_ccpa.json")) as f:
        doc = json.load(f)
    doc["not_a_real_field"] = True

    errors = validate_v1(doc)
    assert len(errors) == 1
    assert "not_a_real_field" in errors[0]
