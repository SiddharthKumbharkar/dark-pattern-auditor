"""Decision complexity metrics (Layer 3): option counts, reading level,
negation density, time on step, total actions required. Pure measurement,
no LLM, no subjective judgement.

Flesch-Kincaid is implemented directly (a documented formula, not a
model) rather than via the `textstat` package, which isn't installed in
this environment -- see signals/claims.py's docstring for the same
reasoning applied to spaCy. The syllable counter is the standard
vowel-group heuristic used by every from-scratch Flesch-Kincaid
implementation; it's an approximation (English spelling isn't phonetic),
not a pronunciation dictionary lookup.
"""

import re
from datetime import datetime
from typing import Dict, List, Optional

_WORD_PATTERN = re.compile(r"[A-Za-z']+")
_SENTENCE_SPLIT_PATTERN = re.compile(r"[.!?]+")
_VOWEL_GROUP_PATTERN = re.compile(r"[aeiouy]+")

_CONSENT_OR_CANCELLATION_KEYWORDS = ("cancel", "cookie", "consent", "unsubscribe", "subscription", "opt out", "opt-out")

# "n't" is handled as its own alternative (not inside the \b...\b group):
# in "don't", there is no word-boundary immediately before the "n" (it's
# adjacent to the word char "o" in "do"), so \bn't\b would never match --
# only the boundary AFTER "t" is meaningful for this one.
_NEGATION_WORDS = re.compile(r"\b(?:not|never|cannot|no|none|nothing|nobody|neither|nor)\b|n't\b", re.IGNORECASE)


def _count_syllables(word: str) -> int:
    word = re.sub(r"[^a-z]", "", word.lower())
    if not word:
        return 0
    groups = _VOWEL_GROUP_PATTERN.findall(word)
    count = len(groups)
    if word.endswith("e") and count > 1:
        count -= 1
    return max(count, 1)


def flesch_kincaid_grade(text: str) -> Optional[float]:
    sentences = [s for s in _SENTENCE_SPLIT_PATTERN.split(text) if s.strip()]
    words = _WORD_PATTERN.findall(text)
    if not sentences or not words:
        return None
    syllables = sum(_count_syllables(w) for w in words)
    grade = 0.39 * (len(words) / len(sentences)) + 11.8 * (syllables / len(words)) - 15.59
    return round(grade, 2)


def count_negations(text: str) -> int:
    return len(_NEGATION_WORDS.findall(text))


def count_double_negatives(text: str) -> int:
    """Sentences containing 2+ negation words each count once."""
    sentences = _SENTENCE_SPLIT_PATTERN.split(text)
    return sum(1 for s in sentences if len(_NEGATION_WORDS.findall(s)) >= 2)


def is_consent_or_cancellation_copy(text: str) -> bool:
    lowered = text.lower()
    return any(kw in lowered for kw in _CONSENT_OR_CANCELLATION_KEYWORDS)


def compute_complexity_metrics(steps: List[Dict], page_texts: List[Optional[str]], interactive_counts: List[Optional[int]]) -> Dict:
    """page_texts and interactive_counts must be the same length as
    steps, aligned by index."""
    option_counts = [
        {"step_id": step["step_id"], "option_count": count}
        for step, count in zip(steps, interactive_counts)
        if count is not None
    ]

    copy_readability = []
    for step, text in zip(steps, page_texts):
        if not text or not is_consent_or_cancellation_copy(text):
            continue
        copy_readability.append(
            {
                "step_id": step["step_id"],
                "flesch_kincaid_grade": flesch_kincaid_grade(text),
                "negation_count": count_negations(text),
                "double_negative_count": count_double_negatives(text),
            }
        )

    time_on_step = []
    for i in range(1, len(steps)):
        seconds = _seconds_between(steps[i - 1].get("timestamp"), steps[i].get("timestamp"))
        time_on_step.append({"step_id": steps[i]["step_id"], "seconds": seconds})

    total_actions_required = sum(
        1 for step in steps if (step.get("action") or {}).get("type") not in (None, "navigate", "unknown")
    )

    return {
        "option_counts": option_counts,
        "copy_readability": copy_readability,
        "time_on_step": time_on_step,
        "total_actions_required": total_actions_required,
    }


def _seconds_between(earlier_iso: Optional[str], later_iso: Optional[str]) -> Optional[float]:
    if not earlier_iso or not later_iso:
        return None
    try:
        earlier = datetime.fromisoformat(earlier_iso)
        later = datetime.fromisoformat(later_iso)
    except ValueError:
        return None
    return round((later - earlier).total_seconds(), 3)
