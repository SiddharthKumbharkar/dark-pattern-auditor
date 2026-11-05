"""Tests for recorder/masking/patterns.py's PII detectors directly (the
lower-level primitives dom_masker.py builds on)."""

from recorder.masking.patterns import (
    find_card_numbers,
    find_emails,
    find_phone_numbers,
    find_protected_spans,
    looks_like_address,
)


def test_find_card_numbers_accepts_luhn_valid_visa_test_number():
    text = "Card: 4111111111111111"
    spans = list(find_card_numbers(text))
    assert len(spans) == 1
    start, end = spans[0]
    assert text[start:end] == "4111111111111111"


def test_find_card_numbers_accepts_spaced_digits():
    text = "Card: 4111 1111 1111 1111"
    spans = list(find_card_numbers(text))
    assert len(spans) == 1


def test_find_card_numbers_rejects_luhn_invalid_sequence():
    text = "Ref: 1234567890123456"
    assert list(find_card_numbers(text)) == []


def test_find_card_numbers_rejects_too_short_sequence():
    text = "PIN: 123456"
    assert list(find_card_numbers(text)) == []


def test_find_emails_basic():
    text = "reach us at hello@example.co.uk please"
    spans = list(find_emails(text))
    assert len(spans) == 1
    start, end = spans[0]
    assert text[start:end] == "hello@example.co.uk"


def test_find_emails_none_when_absent():
    assert list(find_emails("no email here")) == []


def test_find_phone_numbers_requires_enough_digits():
    assert list(find_phone_numbers("qty 12345")) == []  # 5 digits, below floor
    assert len(list(find_phone_numbers("call 555-123-4567"))) == 1  # 10 digits


def test_find_phone_numbers_does_not_swallow_trailing_whitespace():
    text = "call 555-123-4567 today"
    start, end = next(iter(find_phone_numbers(text)))
    assert text[start:end] == "555-123-4567"
    assert not text[start:end].endswith(" ")


def test_looks_like_address_requires_keyword_and_digit():
    assert looks_like_address("42 Main Street") is True
    assert looks_like_address("Main Street") is False  # no digit
    assert looks_like_address("Item #42 in the catalog") is False  # no address keyword


def test_find_protected_spans_matches_price_and_urgency():
    text = "Only 2 left in stock! Rs. 899"
    spans = list(find_protected_spans(text))
    assert len(spans) >= 2
