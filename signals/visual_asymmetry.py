"""Visual asymmetry between opposing choice pairs (accept/reject,
keep/cancel, yes/no, subscribe/decline) -- pure measurement over already-
captured computed-CSS records (recorder/evidence_probe.py), no LLM,
no subjective judgement (Layer 3).

Pairing: for each opposing-pattern, every "positive" (accept/keep/yes/
subscribe-shaped) element is paired with its nearest "negative"
(reject/cancel/no/decline-shaped) element by bounding-box center distance
-- a spatial proximity heuristic, not a DOM-parent-relationship one
(the computed-styles capture is a flat list of interactive elements, not
a tree), disclosed as a scoped, deterministic choice.
"""

import re
from typing import Dict, List, Optional, Tuple

_PAIR_PATTERNS = [
    (
        "accept_reject",
        re.compile(r"\b(accept|agree|allow|yes|ok|got it|continue)\b", re.IGNORECASE),
        re.compile(r"\b(reject|decline|deny|no thanks|no|refuse)\b", re.IGNORECASE),
    ),
    (
        "keep_cancel",
        re.compile(r"\bkeep\b", re.IGNORECASE),
        re.compile(r"\bcancel\b", re.IGNORECASE),
    ),
    (
        "subscribe_decline",
        re.compile(r"\bsubscribe\b", re.IGNORECASE),
        re.compile(r"\b(decline|no thanks|unsubscribe)\b", re.IGNORECASE),
    ),
]

_COLOR_PATTERN = re.compile(r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)")


def _parse_rgb(css_color: Optional[str]) -> Optional[Tuple[float, float, float]]:
    if not css_color:
        return None
    match = _COLOR_PATTERN.search(css_color)
    if not match:
        return None
    return tuple(float(g) for g in match.groups())


def _relative_luminance(rgb: Tuple[float, float, float]) -> float:
    def channel(c: float) -> float:
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def wcag_contrast_ratio(color_a: Optional[str], color_b: Optional[str]) -> Optional[float]:
    """Standard WCAG contrast formula: (L_lighter + 0.05) / (L_darker + 0.05)."""
    rgb_a, rgb_b = _parse_rgb(color_a), _parse_rgb(color_b)
    if rgb_a is None or rgb_b is None:
        return None
    l1, l2 = _relative_luminance(rgb_a), _relative_luminance(rgb_b)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def _own_contrast(element: Dict) -> Optional[float]:
    return wcag_contrast_ratio(element.get("color"), element.get("background_color"))


def _center(element: Dict) -> Tuple[float, float]:
    box = element.get("bounding_box") or {}
    return (
        box.get("x", 0) + box.get("width", 0) / 2,
        box.get("y", 0) + box.get("height", 0) / 2,
    )


def _distance(a: Dict, b: Dict) -> float:
    ax, ay = _center(a)
    bx, by = _center(b)
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5


def find_opposing_pairs(elements: List[Dict]) -> List[Tuple[str, Dict, Dict]]:
    pairs: List[Tuple[str, Dict, Dict]] = []
    used_negative_ids = set()

    for pattern_name, positive_re, negative_re in _PAIR_PATTERNS:
        positives = [el for el in elements if el.get("text") and positive_re.search(el["text"])]
        negatives = [el for el in elements if el.get("text") and negative_re.search(el["text"])]

        for positive in positives:
            candidates = [n for n in negatives if id(n) not in used_negative_ids]
            if not candidates:
                continue
            nearest = min(candidates, key=lambda n: _distance(positive, n))
            used_negative_ids.add(id(nearest))
            pairs.append((pattern_name, positive, nearest))

    return pairs


def compute_visual_asymmetry(step_id: int, elements: List[Dict]) -> List[Dict]:
    results = []
    for pattern_name, positive, negative in find_opposing_pairs(elements):
        pos_box = positive.get("bounding_box") or {}
        neg_box = negative.get("bounding_box") or {}
        pos_area = pos_box.get("width", 0) * pos_box.get("height", 0)
        neg_area = neg_box.get("width", 0) * neg_box.get("height", 0)
        pos_contrast, neg_contrast = _own_contrast(positive), _own_contrast(negative)
        pos_font, neg_font = positive.get("font_size_px"), negative.get("font_size_px")
        # dom_order (document encounter order), not tab_index -- native
        # buttons/links default tab_index to 0 whether or not a tabindex
        # attribute was ever set, so it doesn't reliably distinguish
        # "explicit tab order" from "default"; dom_order is always present
        # and always comparable.
        pos_order, neg_order = positive.get("dom_order"), negative.get("dom_order")

        results.append(
            {
                "step_id": step_id,
                "pair_pattern": pattern_name,
                "positive_selector": positive.get("selector"),
                "negative_selector": negative.get("selector"),
                "positive_text": positive.get("text", ""),
                "negative_text": negative.get("text", ""),
                "area_ratio": (pos_area / neg_area) if neg_area else None,
                "contrast_ratio": (pos_contrast / neg_contrast) if (pos_contrast and neg_contrast) else None,
                "font_size_ratio": (pos_font / neg_font) if (pos_font and neg_font) else None,
                "vertical_position_delta_px": pos_box.get("y", 0) - neg_box.get("y", 0),
                "tab_order_delta": (pos_order - neg_order) if (pos_order is not None and neg_order is not None) else 0,
                "positive_below_fold": bool(positive.get("is_below_fold")),
                "negative_below_fold": bool(negative.get("is_below_fold")),
            }
        )
    return results
