"""Tests for journey/schema_migration.py -- the v1-to-v2 migration shim
and the v2 loader (load_episode)."""

import json
import os

import pytest

from journey.manifest import MANIFEST_FILENAME
from journey.schema_migration import (
    SchemaValidationError,
    load_episode,
    migrate_v1_to_v2,
    validate_v2,
)

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _golden_v1():
    with open(os.path.join(FIXTURES_DIR, "golden_journey_ccpa.json")) as f:
        return json.load(f)


def test_migrated_document_validates_against_v2_schema():
    v2_doc = migrate_v1_to_v2(_golden_v1())
    assert validate_v2(v2_doc) == []


def test_every_v1_field_is_preserved_unchanged():
    v1_doc = _golden_v1()
    v2_doc = migrate_v1_to_v2(v1_doc)
    for key, value in v1_doc.items():
        assert v2_doc[key] == value, f"v1 field {key!r} changed during migration"


def test_schema_version_is_set_to_2():
    v2_doc = migrate_v1_to_v2(_golden_v1())
    assert v2_doc["schema_version"] == 2


def test_episode_block_derivation():
    v2_doc = migrate_v1_to_v2(_golden_v1(), operator="alice")
    episode = v2_doc["episode"]
    assert episode["episode_id"] == "golden_fixture_audit"
    assert episode["site_id"] == "shop.example.com"
    assert episode["site_domain"] == "shop.example.com"
    assert episode["sector"] == "ecommerce"
    assert episode["goal"] is None
    assert episode["revisit_index"] == 0
    assert episode["device_context"] == "desktop"
    assert episode["locale"] is None
    assert episode["paired_episode_id"] is None
    assert episode["collection_mode"] == "manual"
    assert episode["operator"] == "alice"


def test_episode_operator_defaults_to_unknown_when_not_supplied():
    v2_doc = migrate_v1_to_v2(_golden_v1())
    assert v2_doc["episode"]["operator"] == "unknown"


def test_steps_block_count_matches_journey_steps():
    v1_doc = _golden_v1()
    v2_doc = migrate_v1_to_v2(v1_doc)
    assert len(v2_doc["steps"]) == len(v1_doc["journey_steps"])


def test_steps_block_field_mapping_for_normal_step():
    v2_doc = migrate_v1_to_v2(_golden_v1())
    step = v2_doc["steps"][1]  # step_id 2: a click with a screenshot/dom
    assert step["step_id"] == 2
    assert step["action"]["type"] == "click"
    assert step["action"]["selector"] is None
    assert step["action"]["bounding_box"] is None
    assert step["action"]["input_redacted"] is False
    assert step["screenshot_path"] == "screenshots/step_002.png"
    assert step["dom_snapshot_path"] == "dom/step_002.html"
    assert step["screenshot_masked_path"] is None
    assert step["network_events"] == []
    assert step["page_url_redacted"] == "https://shop.example.com/p/wireless-mouse"
    assert step["viewport"] == {"width": 1440, "height": 900}
    assert step["capture_error"] is None
    assert step["tab_id"] == "main"


def test_steps_block_excluded_step_has_null_artifact_paths():
    v2_doc = migrate_v1_to_v2(_golden_v1())
    excluded_step = v2_doc["steps"][3]  # step_id 4: capture_excluded
    assert excluded_step["screenshot_path"] is None
    assert excluded_step["dom_snapshot_path"] is None


def test_outcome_steps_to_complete_matches_step_count():
    v1_doc = _golden_v1()
    v2_doc = migrate_v1_to_v2(v1_doc)
    assert v2_doc["outcome"]["steps_to_complete"] == len(v1_doc["journey_steps"])


def test_outcome_first_and_final_price_derivation():
    v2_doc = migrate_v1_to_v2(_golden_v1())
    outcome = v2_doc["outcome"]
    assert outcome["first_price_shown"] == {"label": "price", "value": 1299.0, "currency": "INR"}
    assert outcome["final_price_shown"] == {"label": "price", "value": 499.0, "currency": "INR"}


def test_outcome_prices_are_null_when_none_ever_shown():
    v1_doc = _golden_v1()
    for step in v1_doc["journey_steps"]:
        step.get("extracted_signals", {})["prices"] = []
    v2_doc = migrate_v1_to_v2(v1_doc)
    assert v2_doc["outcome"]["first_price_shown"] is None
    assert v2_doc["outcome"]["final_price_shown"] is None


def test_outcome_goal_achieved_and_abandoned_reason_are_null_not_fabricated():
    v2_doc = migrate_v1_to_v2(_golden_v1())
    assert v2_doc["outcome"]["goal_achieved"] is None
    assert v2_doc["outcome"]["abandoned_reason"] is None


def test_privacy_validation_passes_for_clean_v1_data():
    v2_doc = migrate_v1_to_v2(_golden_v1())
    assert v2_doc["privacy"]["validation_passed"] is True
    assert v2_doc["privacy"]["redactions_applied"] == []
    assert v2_doc["privacy"]["masker_version"] is None


def test_privacy_validation_fails_when_a_step_carries_a_raw_unmasked_value():
    v1_doc = _golden_v1()
    v1_doc["journey_steps"][0]["user_action"]["input_value_masked"] = "4111111111111111"
    v2_doc = migrate_v1_to_v2(v1_doc)
    assert v2_doc["privacy"]["validation_passed"] is False


def test_placeholder_blocks_are_empty_objects():
    v2_doc = migrate_v1_to_v2(_golden_v1())
    assert v2_doc["evidence"] == {}
    assert v2_doc["attributes"] == {}
    assert v2_doc["ccpa_verdict"] == {}
    assert v2_doc["mechanism_verdict"] == {}


# -- load_episode() (the v2 loader) --------------------------------------


def test_load_episode_migrates_a_v1_file_on_disk(tmp_path):
    path = os.path.join(str(tmp_path), "journey.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(_golden_v1(), f)

    doc = load_episode(path)
    assert doc["schema_version"] == 2
    assert validate_v2(doc) == []


def test_load_episode_picks_up_operator_from_sibling_run_manifest(tmp_path):
    episode_dir = str(tmp_path)
    with open(os.path.join(episode_dir, "journey.json"), "w", encoding="utf-8") as f:
        json.dump(_golden_v1(), f)
    with open(os.path.join(episode_dir, MANIFEST_FILENAME), "w", encoding="utf-8") as f:
        json.dump({"operator": "bob"}, f)

    doc = load_episode(os.path.join(episode_dir, "journey.json"))
    assert doc["episode"]["operator"] == "bob"


def test_load_episode_returns_v2_file_as_is(tmp_path):
    path = os.path.join(str(tmp_path), "episode.json")
    with open(os.path.join(FIXTURES_DIR, "episode_v2_example.json")) as f:
        v2_doc = json.load(f)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(v2_doc, f)

    loaded = load_episode(path)
    assert loaded == v2_doc


def test_load_episode_raises_on_unsupported_schema_version(tmp_path):
    path = os.path.join(str(tmp_path), "journey.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"schema_version": 99}, f)

    with pytest.raises(SchemaValidationError):
        load_episode(path)
