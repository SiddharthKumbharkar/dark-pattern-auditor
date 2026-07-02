"""URL-pattern rules for pages that must never be captured (CLAUDE.md)."""

import os

DEFAULT_EXCLUSION_PATTERNS = [
    "/payment",
    "/pay/",
    "/razorpay",
    "/stripe",
    "/checkout/payment",
    "/billing/pay",
    "/order/pay",
    "/cashfree",
    "/payu",
    "/paytm/pay",
]


def load_exclusion_patterns() -> list[str]:
    extra = os.environ.get("EXTRA_EXCLUSION_PATTERNS", "")
    extra_patterns = [p.strip() for p in extra.split(",") if p.strip()]
    return DEFAULT_EXCLUSION_PATTERNS + extra_patterns
