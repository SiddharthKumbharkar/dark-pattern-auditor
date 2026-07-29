"""Tests for recorder/masking/dom_masker.py.

No browser needed -- mask_dom_html takes a plain HTML string and a list of
plain dicts for form-field metadata.
"""

from recorder.masking.dom_masker import mask_dom_html
from recorder.masking.placeholders import (
    PLACEHOLDER_ADDRESS,
    PLACEHOLDER_CARD,
    PLACEHOLDER_EMAIL,
    PLACEHOLDER_PASSWORD,
    PLACEHOLDER_PHONE,
)


def _masked(html, form_fields=None):
    return mask_dom_html(html, form_fields or []).masked_html


# -- ALLOWLIST: every preserved category must survive masking unchanged --


def test_price_text_survives():
    html = "<p>Rs. 8,999</p>"
    assert "Rs. 8,999" in _masked(html)


def test_currency_amount_survives():
    html = "<p>₹1,299.00</p>"
    assert "₹1,299.00" in _masked(html)


def test_countdown_timer_element_survives():
    html = '<div class="countdown-timer" id="deal-timer">Ends in 02:15:00</div>'
    assert "Ends in 02:15:00" in _masked(html)


def test_scarcity_text_survives():
    html = "<p>Only 2 left in stock!</p>"
    assert "Only 2 left in stock!" in _masked(html)


def test_social_proof_text_survives():
    html = "<p>3 people are viewing this</p>"
    assert "3 people are viewing this" in _masked(html)


def test_urgency_copy_survives():
    html = "<p>Hurry, offer expires soon!</p>"
    result = _masked(html)
    assert "Hurry" in result
    assert "offer expires" in result


def test_button_label_survives():
    html = '<button type="button">Add to cart</button>'
    assert "Add to cart" in _masked(html)


def test_button_label_with_phone_shaped_text_still_survives():
    # Whole-node structural allowlist: a button's role protects its own
    # text even if it happens to contain a phone-shaped number.
    html = '<button type="button">Call 555-999-8888 now</button>'
    assert "555-999-8888" in _masked(html)


def test_cookie_consent_banner_text_survives():
    html = '<div class="cookie-consent-banner">We use cookies to improve your experience.</div>'
    assert "We use cookies to improve your experience." in _masked(html)


def test_heading_survives():
    html = "<h1>Sound that disappears into the moment.</h1>"
    assert "Sound that disappears into the moment." in _masked(html)


def test_error_message_survives():
    html = '<div class="error-message" role="alert">Please enter a valid quantity.</div>'
    assert "Please enter a valid quantity." in _masked(html)


def test_allowlisted_phrase_survives_even_when_mixed_with_real_pii_in_the_same_node():
    # Span-level protection: the scarcity phrase itself is untouched, but
    # the email in the SAME text node is still redacted -- whole-node
    # exemption would leak the email here.
    html = "<p>Only 2 left in stock! Contact support@example.com for help.</p>"
    result = _masked(html)
    assert "Only 2 left in stock!" in result
    assert "support@example.com" not in result
    assert PLACEHOLDER_EMAIL in result


# -- DENYLIST: PII content -------------------------------------------------


def test_email_in_plain_text_is_redacted():
    html = "<p>Contact us at jane.doe@example.com</p>"
    result = _masked(html)
    assert "jane.doe@example.com" not in result
    assert PLACEHOLDER_EMAIL in result


def test_phone_number_in_plain_text_is_redacted():
    html = "<p>Call 555-123-4567 for support</p>"
    result = _masked(html)
    assert "555-123-4567" not in result
    assert PLACEHOLDER_PHONE in result


def test_short_numbers_are_not_treated_as_phone_numbers():
    html = "<p>Order #12345 confirmed. Quantity: 3</p>"
    result = _masked(html)
    assert result == html  # nothing redacted -- too short to be a phone number


def test_luhn_valid_card_number_is_redacted():
    html = "<p>Card on file: 4111 1111 1111 1111</p>"
    result = _masked(html)
    assert "4111 1111 1111 1111" not in result
    assert PLACEHOLDER_CARD in result


def test_luhn_invalid_digit_sequence_is_not_treated_as_a_card():
    # Same length/grouping as a real card number but fails the Luhn
    # checksum -- must not be labeled [CARD]. It's still a long digit
    # run, though, so the phone heuristic legitimately claims it instead
    # (this tool favors an occasional over-redaction of a non-PII
    # reference-shaped number over under-redacting real PII).
    html = "<p>Reference: 1234 5678 9012 3456</p>"
    result = _masked(html)
    assert PLACEHOLDER_CARD not in result
    assert "1234 5678 9012 3456" not in result


def test_address_like_text_is_redacted():
    html = "<p>Ship to: 42 Main Street, Apt 4B</p>"
    result = _masked(html)
    assert "42 Main Street" not in result
    assert PLACEHOLDER_ADDRESS in result


def test_plain_text_with_no_pii_and_no_allowlist_match_is_untouched():
    html = "<p>Free shipping on orders over Rs. 500 within India.</p>"
    result = _masked(html)
    assert "Free shipping on orders over Rs. 500 within India." in result


# -- DENYLIST: form fields ---------------------------------------------


def _field(selector, name, field_type, autocomplete="", has_value=True, box=None):
    return {
        "selector": selector,
        "name": name,
        "id": "",
        "type": field_type,
        "autocomplete": autocomplete,
        "has_value": has_value,
        "bounding_box": box or {"x": 0, "y": 0, "width": 10, "height": 10},
    }


def test_password_type_field_is_redacted_unconditionally():
    html = '<input type="password" name="pwd">'
    result = mask_dom_html(html, [_field("input", "pwd", "password")])
    assert PLACEHOLDER_PASSWORD in result.masked_html
    assert "password_field" in result.redaction_kinds


def test_email_type_field_is_redacted_unconditionally():
    html = '<input type="email" name="email">'
    result = mask_dom_html(html, [_field("input", "email", "email")])
    assert PLACEHOLDER_EMAIL in result.masked_html
    assert "email_field" in result.redaction_kinds


def test_tel_type_field_is_redacted_unconditionally():
    html = '<input type="tel" name="phone">'
    result = mask_dom_html(html, [_field("input", "phone", "tel")])
    assert PLACEHOLDER_PHONE in result.masked_html
    assert "tel_field" in result.redaction_kinds


def test_denylisted_field_name_is_redacted():
    html = '<input type="text" name="card_number">'
    result = mask_dom_html(html, [_field("input", "card_number", "text")])
    assert "[REDACTED:card_number]" in result.masked_html
    assert "sensitive_field" in result.redaction_kinds


def test_configurable_field_denylist_overrides_default():
    html = '<input type="text" name="custom_secret">'
    result = mask_dom_html(html, [_field("input", "custom_secret", "text")], field_denylist=["custom_secret"])
    assert "[REDACTED:custom_secret]" in result.masked_html


def test_field_with_no_value_is_left_alone():
    html = '<input type="password" name="pwd">'
    result = mask_dom_html(html, [_field("input", "pwd", "password", has_value=False)])
    assert result.redaction_kinds == []


def test_unrelated_field_is_not_redacted():
    html = '<input type="number" name="quantity" value="3">'
    result = mask_dom_html(html, [_field("input", "quantity", "number")])
    # BeautifulSoup re-serializes (attribute order, self-closing syntax),
    # so this checks semantic content rather than byte-identical HTML.
    assert 'value="3"' in result.masked_html
    assert result.redaction_kinds == []


def test_form_field_box_is_returned_for_screenshot_masking():
    html = '<input type="password" name="pwd">'
    box = {"x": 10, "y": 20, "width": 100, "height": 30}
    result = mask_dom_html(html, [_field("input", "pwd", "password", box=box)])
    assert box in result.redacted_boxes


def test_textarea_value_is_redacted_as_element_text_not_attribute():
    html = '<textarea name="shipping_address">secret address contents</textarea>'
    result = mask_dom_html(html, [_field("textarea", "shipping_address", "text", has_value=True)])
    assert "secret address contents" not in result.masked_html
