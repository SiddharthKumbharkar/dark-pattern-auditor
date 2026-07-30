"""Tests for recorder/masking/network_masker.py -- the network-log
redaction stage. Header/cookie/token VALUES must never survive into
mask_network_event's output, only header NAMES for anything withheld.
"""

from recorder.masking.network_masker import mask_network_event, redact_headers


# -- redact_headers: NAMES only, never values -----------------------------


def test_authorization_header_name_is_withheld():
    assert redact_headers({"Authorization": "Bearer abc123secret"}) == ["authorization"]


def test_cookie_header_name_is_withheld():
    assert redact_headers({"Cookie": "session=abc123"}) == ["cookie"]


def test_set_cookie_header_name_is_withheld():
    assert redact_headers({"Set-Cookie": "session=abc123; HttpOnly"}) == ["set-cookie"]


def test_api_key_header_variants_are_withheld():
    assert redact_headers({"X-API-Key": "sk-abc123"}) == ["x-api-key"]
    assert redact_headers({"api-key": "sk-abc123"}) == ["api-key"]
    assert redact_headers({"ApiKey": "sk-abc123"}) == ["apikey"]


def test_header_name_matching_is_case_insensitive():
    assert redact_headers({"AUTHORIZATION": "Bearer x"}) == ["authorization"]
    assert redact_headers({"CoOkIe": "x=y"}) == ["cookie"]


def test_bearer_token_shaped_value_is_withheld_regardless_of_header_name():
    # A bearer token can show up under a non-denylisted header name (e.g.
    # a custom "X-Upstream-Auth") -- the VALUE shape alone must trigger
    # withholding, not just the well-known names.
    assert redact_headers({"X-Upstream-Auth": "Bearer eyJhbGciOiJIUzI1NiJ9.xyz"}) == ["x-upstream-auth"]


def test_ordinary_headers_are_never_withheld():
    assert redact_headers({"Content-Type": "application/json", "Accept": "*/*"}) == []


def test_no_headers_returns_empty_list():
    assert redact_headers(None) == []
    assert redact_headers({}) == []


def test_multiple_sensitive_headers_all_named_and_sorted():
    headers = {"Cookie": "a=b", "Authorization": "Bearer x", "Content-Type": "application/json"}
    assert redact_headers(headers) == ["authorization", "cookie"]


def test_redacted_header_names_never_contain_the_actual_value():
    # A defense-in-depth check: none of the withheld NAMES should ever
    # accidentally be (or contain) the secret VALUE itself.
    names = redact_headers({"Authorization": "Bearer super-secret-token-xyz"})
    assert all("super-secret-token-xyz" not in n for n in names)


# -- mask_network_event: full event shape --------------------------------


def test_mask_network_event_strips_header_dicts_entirely():
    raw = {
        "method": "POST",
        "url": "https://api.example.com/checkout?token=abc123",
        "status": 200,
        "resource_type": "xhr",
        "request_id": "req-1",
        "request_headers": {"Authorization": "Bearer super-secret", "Content-Type": "application/json"},
        "response_headers": {"Set-Cookie": "sess=xyz"},
    }
    event = mask_network_event(raw)

    assert "request_headers" not in event
    assert "response_headers" not in event
    assert "super-secret" not in str(event)
    assert "xyz" not in event["url_redacted"]  # cookie value never leaked via url either
    # Content-Type is neither a denylisted name nor bearer-shaped -- must
    # not be withheld just because it rode along with Authorization.
    # Set-Cookie came from response_headers -- both sides are combined.
    assert event["redacted_headers"] == ["authorization", "set-cookie"]


def test_mask_network_event_combines_request_and_response_redacted_headers():
    raw = {
        "method": "GET", "url": "https://x.test/", "status": 200, "resource_type": "fetch", "request_id": "r1",
        "request_headers": {"Authorization": "Bearer x"},
        "response_headers": {"Set-Cookie": "a=b"},
    }
    event = mask_network_event(raw)
    assert event["redacted_headers"] == ["authorization", "set-cookie"]


def test_mask_network_event_url_is_redacted_via_redact_url():
    raw = {
        "method": "GET", "url": "https://x.test/?session=abc123&qty=2",
        "status": 200, "resource_type": "xhr", "request_id": "r1",
    }
    event = mask_network_event(raw)
    assert "abc123" not in event["url_redacted"]
    assert "qty=2" in event["url_redacted"]


def test_mask_network_event_respects_custom_query_param_denylist():
    raw = {
        "method": "GET", "url": "https://x.test/?custom=secret&qty=2",
        "status": 200, "resource_type": "xhr", "request_id": "r1",
    }
    event = mask_network_event(raw, query_param_denylist=["custom"])
    assert "secret" not in event["url_redacted"]
    assert "qty=2" in event["url_redacted"]


def test_mask_network_event_no_sensitive_headers_yields_empty_redacted_list():
    raw = {
        "method": "GET", "url": "https://x.test/", "status": 200, "resource_type": "document", "request_id": "r1",
        "request_headers": {"Accept": "text/html"},
    }
    event = mask_network_event(raw)
    assert event["redacted_headers"] == []


def test_mask_network_event_missing_optional_fields_default_sensibly():
    event = mask_network_event({"url": "https://x.test/"})
    assert event["method"] == ""
    assert event["status"] is None
    assert event["resource_type"] == ""
    assert event["request_id"] == ""
    assert event["redacted_headers"] == []


def test_mask_network_event_output_has_exactly_the_expected_keys():
    event = mask_network_event({"method": "GET", "url": "https://x.test/", "status": 200, "resource_type": "xhr", "request_id": "r1"})
    assert set(event.keys()) == {"method", "url_redacted", "status", "resource_type", "request_id", "redacted_headers"}
