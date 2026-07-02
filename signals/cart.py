"""Cart item extraction and diffing (Layer 3).

Pure functions only: no Playwright, no file I/O, no LLM calls.
"""

import re
from html.parser import HTMLParser
from typing import Dict, List, Optional

from signals.price import PRICE_PATTERNS

_SKIP_PATTERNS = frozenset(
    {
        "subtotal",
        "total",
        "shipping",
        "handling",
        "fee",
        "tax",
        "item",
        "qty",
        "price",
        "delivery",
    }
)


class _CartRowParser(HTMLParser):
    """Splits <table> rows into per-cell text, so name/quantity/price stay separate."""

    def __init__(self):
        super().__init__()
        self.rows: List[List[str]] = []
        self._table_depth = 0
        self._current_row: Optional[List[str]] = None
        self._current_cell_parts: Optional[List[str]] = None

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "table":
            self._table_depth += 1
        elif tag == "tr" and self._table_depth > 0:
            self._current_row = []
        elif tag in ("td", "th") and self._current_row is not None:
            self._current_cell_parts = []

    def handle_data(self, data):
        if self._current_cell_parts is not None:
            self._current_cell_parts.append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ("td", "th") and self._current_cell_parts is not None:
            text = " ".join(part.strip() for part in self._current_cell_parts if part.strip())
            self._current_row.append(text)
            self._current_cell_parts = None
        elif tag == "tr" and self._current_row is not None:
            self.rows.append(self._current_row)
            self._current_row = None
        elif tag == "table" and self._table_depth > 0:
            self._table_depth -= 1


def _should_skip_row(cells: List[str]) -> bool:
    if len(cells) < 2:
        return True
    first_cell = cells[0].strip().lower()
    if not first_cell:
        return True
    return any(pattern in first_cell for pattern in _SKIP_PATTERNS)


def _row_to_item(cells: List[str]) -> Optional[Dict]:
    if _should_skip_row(cells):
        return None

    name = cells[0].strip()
    if not name:
        return None

    if len(cells) >= 3:
        price_cell = cells[2]
        quantity = 1
        qty_match = re.search(r"\d+", cells[1])
        if qty_match:
            quantity = int(qty_match.group())
    else:
        price_cell = cells[1]
        quantity = 1

    if not any(pattern.search(price_cell) for pattern in PRICE_PATTERNS):
        return None

    return {"name": name, "quantity": quantity, "user_selected": None}


def extract_cart_items(visible_text: List[str], dom_html: str) -> List[Dict]:
    if not dom_html:
        return []

    parser = _CartRowParser()
    parser.feed(dom_html)

    items = []
    for cells in parser.rows:
        item = _row_to_item(cells)
        if item is not None:
            items.append(item)
    return items


def _normalize(text: Optional[str]) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _names_match(a: str, b: str) -> bool:
    return bool(a) and bool(b) and (a in b or b in a)


def compute_cart_diff(
    previous_items: List[Dict],
    current_items: List[Dict],
    user_actions: List[Dict],
) -> List[Dict]:
    previous_names = [_normalize(item.get("name")).lower() for item in previous_items]

    result = []
    for item in current_items:
        name = _normalize(item.get("name")).lower()
        was_present_before = any(_names_match(name, prev_name) for prev_name in previous_names)

        if was_present_before:
            # Already in an earlier step's cart, so the user must have added
            # it at some point before now — carry it forward as selected.
            result.append(
                {
                    "name": item.get("name"),
                    "quantity": item.get("quantity"),
                    "user_selected": True,
                    "newly_added": False,
                }
            )
            continue

        matched = any(
            action.get("action_type") == "click"
            and action.get("target_text")
            and _names_match(name, _normalize(action["target_text"]).lower())
            for action in user_actions
        )
        result.append(
            {
                "name": item.get("name"),
                "quantity": item.get("quantity"),
                "user_selected": matched,
                "newly_added": True,
            }
        )

    return result
