"""Tests for config/settings.py -- the typed config.yaml loader."""

import os

import pytest
import yaml

from config.settings import DEFAULT_GOALS, PROJECT_ROOT, ConfigError, load_config, resolve_path


def test_defaults_when_no_file_present():
    cfg = load_config(path="/definitely/not/a/real/path/config.yaml")
    assert cfg.pipeline.mode == "both"
    assert cfg.privacy.enabled is True
    assert cfg.privacy.strict is False
    assert cfg.capture.screenshot_full_page is True
    assert cfg.capture.capture_network is False
    assert [g.id for g in cfg.goals] == [g.id for g in DEFAULT_GOALS]
    assert cfg.revisit.offsets_hours == [24, 72]
    assert cfg.output.root == "storage"
    assert cfg.cost.log_enabled is False


def _write_yaml(tmp_path, content: dict) -> str:
    path = os.path.join(str(tmp_path), "config.yaml")
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(content, f)
    return path


def test_overrides_are_applied(tmp_path):
    path = _write_yaml(
        tmp_path,
        {
            "pipeline": {"mode": "mechanism"},
            "privacy": {"enabled": False, "strict": True},
            "output": {"root": "/tmp/my-episodes"},
            "revisit": {"offsets_hours": [12]},
        },
    )
    cfg = load_config(path=path)
    assert cfg.pipeline.mode == "mechanism"
    assert cfg.privacy.enabled is False
    assert cfg.privacy.strict is True
    assert cfg.output.root == "/tmp/my-episodes"
    assert cfg.revisit.offsets_hours == [12]
    # untouched sections keep their defaults
    assert cfg.capture.screenshot_full_page is True


def test_partial_file_falls_back_to_defaults_for_missing_sections(tmp_path):
    path = _write_yaml(tmp_path, {"cost": {"log_enabled": True}})
    cfg = load_config(path=path)
    assert cfg.cost.log_enabled is True
    assert cfg.pipeline.mode == "both"


def test_invalid_mode_raises(tmp_path):
    path = _write_yaml(tmp_path, {"pipeline": {"mode": "bogus"}})
    with pytest.raises(ConfigError):
        load_config(path=path)


def test_non_bool_privacy_field_raises(tmp_path):
    path = _write_yaml(tmp_path, {"privacy": {"enabled": "yes"}})
    with pytest.raises(ConfigError):
        load_config(path=path)


def test_empty_output_root_raises(tmp_path):
    path = _write_yaml(tmp_path, {"output": {"root": ""}})
    with pytest.raises(ConfigError):
        load_config(path=path)


def test_negative_revisit_offset_raises(tmp_path):
    path = _write_yaml(tmp_path, {"revisit": {"offsets_hours": [24, -1]}})
    with pytest.raises(ConfigError):
        load_config(path=path)


def test_custom_goals_replace_seed_goals(tmp_path):
    path = _write_yaml(
        tmp_path, {"goals": [{"id": "custom_goal", "description": "A custom goal."}]}
    )
    cfg = load_config(path=path)
    assert [g.id for g in cfg.goals] == ["custom_goal"]


def test_duplicate_goal_id_raises(tmp_path):
    path = _write_yaml(
        tmp_path,
        {"goals": [{"id": "dup", "description": "one"}, {"id": "dup", "description": "two"}]},
    )
    with pytest.raises(ConfigError):
        load_config(path=path)


def test_goal_missing_description_raises(tmp_path):
    path = _write_yaml(tmp_path, {"goals": [{"id": "no_desc"}]})
    with pytest.raises(ConfigError):
        load_config(path=path)


def test_repo_config_yaml_loads_and_validates():
    # The shipped config.yaml itself must be valid and match the spec.
    cfg = load_config()
    assert cfg.pipeline.mode == "both"
    assert [g.id for g in cfg.goals] == [
        "purchase_cheapest",
        "complete_signup",
        "cancel_subscription",
        "reject_cookies",
        "unsubscribe_email",
        "decline_addon",
        "disable_notifications",
        "track_flight",
    ]
    assert cfg.revisit.offsets_hours == [24, 72]
    assert cfg.output.root == "storage"


def test_resolve_path_relative_anchors_to_project_root():
    assert resolve_path("storage") == os.path.join(PROJECT_ROOT, "storage")


def test_resolve_path_absolute_passthrough():
    assert resolve_path("/abs/path") == "/abs/path"
