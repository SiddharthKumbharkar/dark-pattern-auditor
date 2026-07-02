"""Masks sensitive form field values before they are written to storage.

Sensitive values must never be written to disk in raw form; this module
must run BEFORE any capture is persisted (see CLAUDE.md Key Design Rules).
"""

SENSITIVE_PATTERNS = [
    "card",
    "cc",
    "cvv",
    "cvc",
    "expiry",
    "expiration",
    "pan",
    "aadhaar",
    "aadhar",
    "ssn",
    "passport",
    "account_number",
    "routing",
    "ifsc",
    "dob",
    "date_of_birth",
    "bank",
    "pin",
    "otp",
    "credit",
    "debit",
]

SENSITIVE_FIELD_TYPES = ["password", "hidden"]


def should_redact(field_name: str, field_type: str, autocomplete: str) -> bool:
    if (field_type or "").strip().lower() in SENSITIVE_FIELD_TYPES:
        return True

    name = (field_name or "").lower()
    autocomplete_value = (autocomplete or "").lower()
    return any(
        pattern in name or pattern in autocomplete_value
        for pattern in SENSITIVE_PATTERNS
    )


def redact_form_value(field_name: str, field_type: str, autocomplete: str, value: str) -> str:
    if should_redact(field_name, field_type, autocomplete):
        return f"[REDACTED:{field_name}]"
    return value
