"""Pre-persistence privacy validation gate (Layer 2).

Every step passes through here (JourneyBuilder.add_step) before it is
appended to a journey, i.e. before anything reaches the journey JSON that
gets written to disk.

Today the only schema field ever populated with a value sourced from raw
user input is user_action.input_value_masked -- see recorder/redaction.py,
which provides the masking primitives (should_redact / redact_form_value)
but is not yet wired into any capture path (no code currently sets
input_value_masked to anything but None). This module is the seam a future
form-capture path plugs into: it enforces that whatever lands in
input_value_masked has actually been through redact_form_value() (i.e.
starts with the "[REDACTED:" sentinel, or is None), catching a raw value
someone forgot to mask before it can be persisted.
"""

from typing import Dict, List

from config.settings import PrivacyConfig

REDACTED_PREFIX = "[REDACTED:"


class PrivacyValidationError(Exception):
    """Raised when privacy.strict is True and a step fails masking validation."""


def find_privacy_violations(user_action: Dict) -> List[str]:
    violations = []
    masked_value = user_action.get("input_value_masked")
    if masked_value is not None and not str(masked_value).startswith(REDACTED_PREFIX):
        violations.append(
            "user_action.input_value_masked carries a value that was not passed through "
            "recorder.redaction.redact_form_value() before capture"
        )
    return violations


def validate_step_privacy(user_action: Dict, cfg: PrivacyConfig) -> List[str]:
    """Returns any violations found. Raises PrivacyValidationError instead,
    without returning, when cfg.strict is True and violations exist."""
    if not cfg.enabled:
        return []

    violations = find_privacy_violations(user_action)
    if violations and cfg.strict:
        raise PrivacyValidationError("; ".join(violations))
    return violations
