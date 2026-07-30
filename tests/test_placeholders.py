"""Tests for recorder/masking/placeholders.py -- the typed placeholder
constants and the redaction-tally helper that feeds
episode.privacy.redactions_applied.
"""

from recorder.masking.placeholders import (
    PLACEHOLDER_ADDRESS,
    PLACEHOLDER_CARD,
    PLACEHOLDER_EMAIL,
    PLACEHOLDER_PASSWORD,
    PLACEHOLDER_PHONE,
    PLACEHOLDER_TOKEN,
    tally_redactions,
)


def test_every_placeholder_is_a_distinct_non_empty_string():
    placeholders = [
        PLACEHOLDER_EMAIL, PLACEHOLDER_PHONE, PLACEHOLDER_CARD,
        PLACEHOLDER_ADDRESS, PLACEHOLDER_PASSWORD, PLACEHOLDER_TOKEN,
    ]
    assert all(isinstance(p, str) and p for p in placeholders)
    assert len(set(placeholders)) == len(placeholders)  # no collisions


def test_tally_redactions_counts_each_kind():
    result = tally_redactions(3, ["email", "email", "card"])
    assert {"step_id": 3, "kind": "card", "count": 1} in result
    assert {"step_id": 3, "kind": "email", "count": 2} in result


def test_tally_redactions_empty_list_returns_empty():
    assert tally_redactions(1, []) == []


def test_tally_redactions_single_kind():
    assert tally_redactions(5, ["password_field"]) == [{"step_id": 5, "kind": "password_field", "count": 1}]


def test_tally_redactions_output_is_sorted_by_kind_for_stable_output():
    result = tally_redactions(1, ["phone", "address", "email"])
    kinds = [r["kind"] for r in result]
    assert kinds == sorted(kinds)


def test_tally_redactions_every_entry_carries_the_given_step_id():
    result = tally_redactions(42, ["email", "card", "phone"])
    assert all(r["step_id"] == 42 for r in result)
