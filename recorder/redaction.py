"""Masks sensitive form field values and URLs before they are written to
storage.

Sensitive values must never be written to disk in raw form; this module
must run BEFORE any capture is persisted (see CLAUDE.md Key Design Rules).
The broader DOM/screenshot/network masking pipeline (recorder/masking/) is
built on top of the primitives here, not the other way around -- this
module has no dependency on recorder/masking/.
"""

import re
from typing import List, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

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
    "name",
    "address",
]

SENSITIVE_FIELD_TYPES = ["password", "hidden"]

# Query param NAMES whose VALUE gets replaced with PLACEHOLDER_TOKEN (the
# key itself is kept -- redacting "?token=[TOKEN]" is more useful
# downstream than deleting the param entirely, per the same
# keep-the-shape-lose-the-value philosophy as redact_form_value below).
DEFAULT_QUERY_PARAM_DENYLIST = [
    "token",
    "session",
    "session_id",
    "sessionid",
    "sid",
    "auth",
    "authorization",
    "api_key",
    "apikey",
    "key",
    "access_token",
    "refresh_token",
    "id_token",
    "jwt",
    "otp",
    "password",
    "pwd",
    "email",
    "phone",
    "card",
    "cvv",
    "ssn",
]

PLACEHOLDER_TOKEN = "[TOKEN]"

# A path segment that looks like an opaque, machine-generated identifier
# (session id, upload token, etc.) rather than meaningful, human-authored
# URL structure. Heuristic, not a guarantee -- see redact_url's docstring.
_OPAQUE_PATH_SEGMENT = re.compile(r"^[A-Za-z0-9_-]{20,}$")


def should_redact(
    field_name: str, field_type: str, autocomplete: str, patterns: Optional[List[str]] = None
) -> bool:
    if (field_type or "").strip().lower() in SENSITIVE_FIELD_TYPES:
        return True

    name = (field_name or "").lower()
    autocomplete_value = (autocomplete or "").lower()
    return any(
        pattern in name or pattern in autocomplete_value
        for pattern in (patterns if patterns is not None else SENSITIVE_PATTERNS)
    )


def redact_form_value(
    field_name: str, field_type: str, autocomplete: str, value: str, patterns: Optional[List[str]] = None
) -> str:
    if should_redact(field_name, field_type, autocomplete, patterns):
        return f"[REDACTED:{field_name}]"
    return value


def redact_url(url: str, query_param_denylist: Optional[List[str]] = None) -> str:
    """Redacts a URL before persistence: denylisted query param VALUES are
    replaced with PLACEHOLDER_TOKEN (the key is kept), path segments that
    look like opaque/machine-generated identifiers are replaced the same
    way, and the fragment is always dropped (a common OAuth-implicit-flow
    token leak vector, e.g. "#access_token=..."). Everything else --
    non-denylisted query params, ordinary path segments -- is left as-is.

    This is a scoped, disclosed heuristic: it does NOT attempt to detect
    sensitive information embedded in ordinary-looking path segments (e.g.
    "/users/12345/profile" is left unchanged), and a param not on the
    denylist is never touched even if its value happens to look sensitive.
    Used for schema v2's page_url_redacted and NetworkEvent.url_redacted
    fields (see recorder/interactive_v2.py, recorder/network_capture.py).
    """
    if not url:
        return url

    denylist = {p.lower() for p in (query_param_denylist or DEFAULT_QUERY_PARAM_DENYLIST)}
    parts = urlsplit(url)

    redacted_query = urlencode(
        [
            (key, PLACEHOLDER_TOKEN if key.lower() in denylist else value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
        ]
    )

    redacted_path = "/".join(
        PLACEHOLDER_TOKEN if _OPAQUE_PATH_SEGMENT.match(segment) else segment
        for segment in parts.path.split("/")
    )

    return urlunsplit((parts.scheme, parts.netloc, redacted_path, redacted_query, ""))
