from urllib.parse import parse_qsl, urlsplit

from recorder.redaction import PLACEHOLDER_TOKEN, redact_form_value, redact_url, should_redact


def test_card_number_field_is_redacted():
    assert should_redact("card_number", "text", "cc-number") is True
    assert redact_form_value("card_number", "text", "cc-number", "4111111111111111") == "[REDACTED:card_number]"


def test_password_type_is_redacted():
    assert should_redact("secret", "password", "") is True
    assert redact_form_value("secret", "password", "", "hunter2") == "[REDACTED:secret]"


def test_name_field_is_redacted():
    # "name" is an explicit denylist entry (a person's name is PII) --
    # this deliberately changed from an earlier version of this module
    # that did not redact name fields.
    assert should_redact("full_name", "text", "name") is True
    assert redact_form_value("full_name", "text", "name", "Jane Doe") == "[REDACTED:full_name]"


def test_unrelated_field_is_not_redacted():
    assert should_redact("quantity", "number", "") is False
    assert redact_form_value("quantity", "number", "", "3") == "3"


def test_email_field_is_not_redacted_by_should_redact_alone():
    # should_redact() is field-name/type/autocomplete-based; a field
    # literally typed/named "email" is not on the SENSITIVE_PATTERNS list
    # itself -- but recorder/masking/dom_masker.py separately redacts
    # type="email" inputs unconditionally (see test_dom_masker.py).
    assert should_redact("email", "email", "email") is False
    assert redact_form_value("email", "email", "email", "jane@example.com") == "jane@example.com"


def _query_dict(url: str) -> dict:
    return dict(parse_qsl(urlsplit(url).query))


def test_redact_url_replaces_denylisted_query_param_values_only():
    result = redact_url("https://shop.example.com/cart?session=abc123&email=a@b.com&qty=2")
    query = _query_dict(result)
    assert query["session"] == PLACEHOLDER_TOKEN
    assert query["email"] == PLACEHOLDER_TOKEN
    assert query["qty"] == "2"  # not denylisted -- kept as-is
    assert urlsplit(result).path == "/cart"


def test_redact_url_strips_fragment():
    result = redact_url("https://api.example.com/track/beacon?uid=42#access_token=abc")
    assert "#" not in result
    assert _query_dict(result)["uid"] == "42"


def test_redact_url_leaves_clean_url_unchanged():
    assert redact_url("https://shop.example.com/product/123") == "https://shop.example.com/product/123"


def test_redact_url_leaves_short_path_segments_alone():
    # A short numeric id is ordinary URL structure, not an opaque token.
    assert redact_url("https://shop.example.com/users/12345/profile") == "https://shop.example.com/users/12345/profile"


def test_redact_url_redacts_opaque_looking_path_segments():
    result = redact_url("https://shop.example.com/reset-password/aZ9fK3mQ7pL2xR8vN4tB6yC1wD5sH0j")
    segments = urlsplit(result).path.split("/")
    assert segments[-1] == PLACEHOLDER_TOKEN
    assert segments[1] == "reset-password"


def test_redact_url_custom_denylist_overrides_default():
    result = redact_url("https://x.test/?qty=2&custom=secret", query_param_denylist=["custom"])
    query = _query_dict(result)
    assert query["custom"] == PLACEHOLDER_TOKEN
    assert query["qty"] == "2"


def test_redact_url_handles_empty_and_none():
    assert redact_url("") == ""
    assert redact_url(None) is None
