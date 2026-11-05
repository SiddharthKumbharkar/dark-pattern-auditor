"""URL-pattern page-skip checks (CLAUDE.md: payment pages are excluded by default)."""

from typing import List, Optional, Tuple

from config.exclusion_rules import load_exclusion_patterns


def is_excluded(url: str, patterns: Optional[List[str]] = None) -> Tuple[bool, str]:
    if patterns is None:
        patterns = load_exclusion_patterns()

    url_lower = (url or "").lower()
    for pattern in patterns:
        if pattern.lower() in url_lower:
            return True, pattern
    return False, ""
