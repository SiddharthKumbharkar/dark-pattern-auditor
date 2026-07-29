"""Price drift across an episode's steps (Layer 3). Pure measurement,
reusing signals/price.py's existing extraction rather than a second
price-detection implementation.
"""

from typing import Dict, List, Optional

from signals.price import extract_prices


def _step_total(page_text: str) -> Optional[float]:
    """The largest price found on a step's page is treated as its
    displayed total -- on a checkout-shaped page a grand-total line is
    reliably the largest number present; per-item prices are smaller.
    Disclosed heuristic, not a semantic "find the total" parser."""
    prices = extract_prices([page_text]) if page_text else []
    if not prices:
        return None
    return max(p["value"] for p in prices)


def compute_price_drift(steps_with_text: List[Dict]) -> Dict:
    """steps_with_text: [{"step_id": int, "page_text": str}], in step order."""
    totals = []
    for entry in steps_with_text:
        total = _step_total(entry.get("page_text") or "")
        if total is not None:
            totals.append((entry["step_id"], total))

    if not totals:
        return {"first_total": None, "final_total": None, "drift": None, "increases": []}

    first_total = totals[0][1]
    final_total = totals[-1][1]

    increases = []
    previous_total = first_total
    for step_id, total in totals[1:]:
        if total > previous_total:
            increases.append({"step_id": step_id, "delta": round(total - previous_total, 2), "new_total": total})
        previous_total = total

    return {
        "first_total": first_total,
        "final_total": final_total,
        "drift": round(final_total - first_total, 2),
        "increases": increases,
    }
