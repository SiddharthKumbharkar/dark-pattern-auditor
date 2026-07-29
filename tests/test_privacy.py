"""Tests for journey/privacy.py -- pre-persistence privacy validation gate."""

import pytest

from config.settings import PrivacyConfig
from journey.privacy import PrivacyValidationError, find_privacy_violations, validate_step_privacy


def test_clean_action_has_no_violations():
    action = {"action_type": "click", "target_text": "Add to Cart", "input_value_masked": None}
    assert find_privacy_violations(action) == []


def test_masked_value_with_redacted_prefix_is_clean():
    action = {"action_type": "form_input", "input_value_masked": "[REDACTED:card_number]"}
    assert find_privacy_violations(action) == []


def test_raw_unmasked_value_is_flagged():
    action = {"action_type": "form_input", "input_value_masked": "4111111111111111"}
    violations = find_privacy_violations(action)
    assert len(violations) == 1
    assert "input_value_masked" in violations[0]


def test_disabled_privacy_skips_validation_entirely():
    action = {"action_type": "form_input", "input_value_masked": "4111111111111111"}
    cfg = PrivacyConfig(enabled=False, strict=True)
    assert validate_step_privacy(action, cfg) == []


def test_non_strict_returns_violations_without_raising():
    action = {"action_type": "form_input", "input_value_masked": "4111111111111111"}
    cfg = PrivacyConfig(enabled=True, strict=False)
    assert len(validate_step_privacy(action, cfg)) == 1


def test_strict_raises_and_aborts():
    action = {"action_type": "form_input", "input_value_masked": "4111111111111111"}
    cfg = PrivacyConfig(enabled=True, strict=True)
    with pytest.raises(PrivacyValidationError):
        validate_step_privacy(action, cfg)


def test_strict_with_clean_action_does_not_raise():
    action = {"action_type": "click", "input_value_masked": None}
    cfg = PrivacyConfig(enabled=True, strict=True)
    assert validate_step_privacy(action, cfg) == []
