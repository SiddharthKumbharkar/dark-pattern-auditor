"""Redacts one CDP network event before it can ever be persisted (Layer 1/
masking). Header/cookie VALUES never appear in the output of this module
-- only the NAMES of headers that were present and are being withheld, so
downstream signals can still see e.g. "this request carried
Authorization" without the token itself ever touching disk.
"""

import re
from typing import Dict, List, Optional

from recorder.redaction import redact_url

_AUTH_HEADER_NAMES = {"authorization", "cookie", "set-cookie", "x-api-key", "api-key", "apikey"}
_BEARER_PATTERN = re.compile(r"bearer\s+\S+", re.IGNORECASE)


def redact_headers(headers: Optional[Dict[str, str]]) -> List[str]:
    """Returns the lowercase NAMES (never values) of headers being
    withheld: any denylisted auth-related header name, or any header
    whose value looks like a bearer token regardless of its name."""
    if not headers:
        return []
    redacted = []
    for name, value in headers.items():
        lower_name = (name or "").lower()
        if lower_name in _AUTH_HEADER_NAMES:
            redacted.append(lower_name)
        elif isinstance(value, str) and _BEARER_PATTERN.search(value):
            redacted.append(lower_name)
    return sorted(set(redacted))


def mask_network_event(raw_event: Dict, query_param_denylist: Optional[List[str]] = None) -> Dict:
    """raw_event carries transient request_headers/response_headers dicts
    that are consumed here and never appear in the returned dict -- only
    `redacted_headers` (names) does."""
    redacted_headers = sorted(
        set(
            redact_headers(raw_event.get("request_headers"))
            + redact_headers(raw_event.get("response_headers"))
        )
    )
    return {
        "method": raw_event.get("method", ""),
        "url_redacted": redact_url(raw_event.get("url", ""), query_param_denylist),
        "status": raw_event.get("status"),
        "resource_type": raw_event.get("resource_type", ""),
        "request_id": raw_event.get("request_id", ""),
        "redacted_headers": redacted_headers,
    }
