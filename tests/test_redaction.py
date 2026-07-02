from recorder.redaction import redact_form_value, should_redact


def test_card_number_field_is_redacted():
    assert should_redact("card_number", "text", "cc-number") is True
    assert redact_form_value("card_number", "text", "cc-number", "4111111111111111") == "[REDACTED:card_number]"


def test_password_type_is_redacted():
    assert should_redact("secret", "password", "") is True
    assert redact_form_value("secret", "password", "", "hunter2") == "[REDACTED:secret]"


def test_name_field_is_not_redacted():
    assert should_redact("full_name", "text", "name") is False
    assert redact_form_value("full_name", "text", "name", "Jane Doe") == "Jane Doe"


def test_email_field_is_not_redacted():
    assert should_redact("email", "email", "email") is False
    assert redact_form_value("email", "email", "email", "jane@example.com") == "jane@example.com"
