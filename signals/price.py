"""Price extraction (Layer 3). Pure functions: no Playwright, no file I/O, no LLM calls."""

import re
from typing import Dict, List, Optional

PRICE_PATTERNS = [
    re.compile(r"₹\s*(?P<amount>\d{1,3}(?:,\d{2,3})*(?:\.\d{1,2})?)"),
    re.compile(r"\bRs\.?\s*(?P<amount>\d{1,3}(?:,\d{2,3})*(?:\.\d{1,2})?)", re.IGNORECASE),
    re.compile(r"\bINR\s*(?P<amount>\d{1,3}(?:,\d{2,3})*(?:\.\d{1,2})?)", re.IGNORECASE),
    re.compile(r"(?<![\d.\w])(?P<amount>\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?)(?!\d)"),
]


def extract_prices(visible_text: List[str], label_hint: Optional[str] = None) -> List[Dict]:
    label = label_hint or "price"
    results: List[Dict] = []
    seen = set()

    for text in visible_text:
        if not text:
            continue
        for pattern in PRICE_PATTERNS:
            for match in pattern.finditer(text):
                amount_str = match.group("amount").replace(",", "")
                try:
                    value = float(amount_str)
                except ValueError:
                    continue
                key = (label, value)
                if key in seen:
                    continue
                seen.add(key)
                results.append({"label": label, "value": value, "currency": "INR"})

    return results


def build_price_timeline(steps: List[Dict]) -> List[Dict]:
    timeline = []
    for step in steps:
        extracted_signals = step.get("extracted_signals") or {}
        timeline.append(
            {
                "step_id": step.get("step_id"),
                "page_type": step.get("page_type"),
                "prices": extracted_signals.get("prices", []),
            }
        )
    return timeline
