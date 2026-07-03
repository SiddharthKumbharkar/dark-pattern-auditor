"""Urgency/scarcity claim and countdown-timer extraction (Layer 3).

Pure functions only: no Playwright, no file I/O, no LLM calls.
"""

import re
from html.parser import HTMLParser
from typing import Dict, List

URGENCY_PHRASES = [
    re.compile(r"only\s+\d+\s+left", re.IGNORECASE),
    re.compile(r"hurry", re.IGNORECASE),
    re.compile(r"limited\s+stock", re.IGNORECASE),
    re.compile(r"selling\s+fast", re.IGNORECASE),
    re.compile(r"just\s+bought", re.IGNORECASE),
    re.compile(r"people\s+are\s+viewing", re.IGNORECASE),
    re.compile(r"ends\s+in", re.IGNORECASE),
    re.compile(r"offer\s+expires", re.IGNORECASE),
    re.compile(r"deal\s+ends", re.IGNORECASE),
    re.compile(r"last\s+chance", re.IGNORECASE),
    re.compile(r"almost\s+gone", re.IGNORECASE),
    re.compile(r"\d+\s+sold\s+in\s+last", re.IGNORECASE),
    re.compile(r"limited\s+time\s+offer", re.IGNORECASE),
    re.compile(r"while\s+stocks?\s+last", re.IGNORECASE),
    re.compile(r"don'?t\s+miss\s+out", re.IGNORECASE),
    re.compile(r"act\s+now", re.IGNORECASE),
    re.compile(r"stock\s+(?:is\s+)?running\s+out", re.IGNORECASE),
    re.compile(r"sale\s+ends\s+soon", re.IGNORECASE),
    re.compile(r"jaldi\s+karo", re.IGNORECASE),  # Hindi: "hurry up"
    re.compile(r"sirf\s+\d+\s+bache", re.IGNORECASE),  # Hindi: "only N left"
    re.compile(r"stock\s+khatam\s+hone\s+wala", re.IGNORECASE),  # Hindi: "stock about to run out"
    re.compile(r"abhi\s+kharido", re.IGNORECASE),  # Hindi: "buy now"
    re.compile(r"jaldi\s+order\s+karein", re.IGNORECASE),  # Hindi: "order quickly"
    re.compile(r"offer\s+khatam\s+hone\s+wala", re.IGNORECASE),  # Hindi: "offer about to end"
    re.compile(r"\b\d+\s+left\b", re.IGNORECASE),
    re.compile(r"\b(only\s+)?\d+\s+(items?\s+)?left\b", re.IGNORECASE),
    re.compile(r"\d+\s+people\s+(bought|viewed|looking)", re.IGNORECASE),
    re.compile(r"\d+\s+people\s+bought\s+this\s+in\s+the\s+last\s+\d+\s+days", re.IGNORECASE),
    re.compile(r"(just\s+)?bought\s+by\s+\d+", re.IGNORECASE),
    re.compile(r"selling\s+fast", re.IGNORECASE),
    re.compile(r"hurry[,!]?", re.IGNORECASE),
    re.compile(r"\d+\s+(others?\s+)?viewing\s+(this|right\s+now)", re.IGNORECASE),
]

SOCIAL_PROOF_PATTERNS = [
    re.compile(r"\d+\s+people\s+bought\s+this\s+in\s+the\s+last\s+\d+\s+days", re.IGNORECASE),
    re.compile(r"\d+\s+people\s+are\s+viewing\s+this", re.IGNORECASE),
    re.compile(r"\d+\s+(others?\s+)?(?:are\s+)?looking\s+at\s+this", re.IGNORECASE),
    re.compile(r"best\s*seller", re.IGNORECASE),
    re.compile(r"\d+\s*(?:crores?|lakhs?)\+?\s+customers", re.IGNORECASE),
    re.compile(r"\d+\s*(?:crores?|lakhs?)\+?\s+(?:products?\s+)?sold", re.IGNORECASE),
    re.compile(r"\d+\s+people\s+(bought|viewed)", re.IGNORECASE),
]

_TIMER_KEYWORDS = ["countdown", "timer", "clock", "time-left"]


def extract_urgency_claims(visible_text: List[str]) -> List[str]:
    results: List[str] = []
    seen = set()

    for text in visible_text:
        if not text or text in seen:
            continue
        if any(pattern.search(text) for pattern in URGENCY_PHRASES):
            seen.add(text)
            results.append(text)

    return results


def extract_social_proof_claims(visible_text: List[str]) -> List[str]:
    results: List[str] = []
    seen = set()

    for text in visible_text:
        if not text or text in seen:
            continue
        if any(pattern.search(text) for pattern in SOCIAL_PROOF_PATTERNS):
            seen.add(text)
            results.append(text)

    return results


class _TimerElementParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.results: List[Dict] = []
        self._stack: List[Dict] = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = {k.lower(): (v or "") for k, v in attrs}
        class_attr = attrs_dict.get("class", "").lower()
        id_attr = attrs_dict.get("id", "").lower()
        is_timer = (
            any(kw in class_attr for kw in _TIMER_KEYWORDS)
            or any(kw in id_attr for kw in _TIMER_KEYWORDS)
            or any(k.startswith("data-countdown") for k in attrs_dict.keys())
        )

        selector = tag
        if id_attr:
            selector += f"#{attrs_dict['id']}"
        elif class_attr:
            classes = class_attr.split()
            if classes:
                selector += f"." + classes[0]

        self._stack.append({"tag": tag, "is_timer": is_timer, "selector": selector, "text": []})

    def handle_data(self, data):
        for frame in self._stack:
            if frame["is_timer"]:
                frame["text"].append(data)

    def handle_endtag(self, tag):
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i]["tag"] == tag:
                frame = self._stack.pop(i)
                if frame["is_timer"]:
                    text_content = "".join(frame["text"]).strip()
                    self.results.append(
                        {"element_selector": frame["selector"], "text_content": text_content}
                    )
                del self._stack[i:]
                break


def extract_timers(dom_html: str) -> List[Dict]:
    try:
        if not dom_html:
            return []
        parser = _TimerElementParser()
        parser.feed(dom_html)
        return parser.results
    except Exception:
        return []
