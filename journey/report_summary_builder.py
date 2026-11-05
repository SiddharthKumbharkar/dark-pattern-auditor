"""Assembles data for the presentation-ready SUMMARY report view -- a
plain-language reading of the exact same frozen episode data the
technical report (journey/report_builder.py + journey/report_html.py)
already renders. This module computes NOTHING new: every fact here is
read straight off episode.mechanism_verdict.computed_output (built by
journey/episode_output_builder.py) or episode.evidence -- no detection
logic, no threshold, no agent behavior lives here. If a verdict needs to
change, that happens upstream; this module only translates an existing
verdict into a sentence a non-technical reader can understand in under a
minute.

Reuses journey/report_builder.py's build_report_data() for the filmstrip/
regions/overall (so the summary and the technical report can never
silently diverge on what actually fired) and adds three presentation-only
things build_report_data() doesn't need for the technical view:
  - ATTRIBUTE_LABELS: attribute code -> plain-English mechanism name.
  - A per-step "what a human would say" sentence, built from the same
    evidence_pointers the technical report already draws bounding boxes
    from -- see _element_phrase() and _asymmetry_sentence() (the latter
    reads episode.evidence.visual_asymmetry's own positive_text/
    negative_text/area_ratio directly, so "X is smaller than Y" is a
    grounded reading of a real measured ratio, never invented).
  - A verdict banner + coverage sentence in plain language, with numbers
    rounded to a severity band (high/medium/low) rather than shown raw.
"""

import os
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from journey.report_builder import build_report_data
from journey.schema_migration import load_episode
from journey.verdict_output_builder import coordinator_pattern_combinations

# Used consistently everywhere an attribute code would otherwise leak into
# the summary view -- see this module's docstring. Exported so
# journey/report_summary_html.py never has to guess a label on its own.
ATTRIBUTE_LABELS: Dict[str, str] = {
    "asymmetry": "Unequal choice prominence",
    "restriction": "Hard-to-exit flow",
    "deception": "Action that doesn't do what it says",
    "complexity": "Unnecessary complexity / overload",
    "covertness": "Disguised or hidden steering",
    "information_hiding": "Important information hidden until commitment",
    "disparate_treatment": "Different treatment for different users",
}

_REGION_LABELS: Dict[str, str] = {
    "cookie_consent_banner": "cookie consent banner",
    "checkout_price_summary": "checkout",
    "cancellation_flow": "cancellation flow",
    "signup_form": "signup form",
    "login_form": "login form",
    "newsletter_modal": "newsletter signup",
    "addon_upsell": "add-on offer",
    "account_settings": "account settings",
    "retention_offer": "retention offer",
    "unclassified": "flow",
}

_GOAL_LABELS: Dict[str, str] = {
    "purchase_cheapest": "Find and buy the cheapest option",
    "complete_signup": "Complete signup",
    "cancel_subscription": "Cancel subscription",
    "reject_cookies": "Reject cookies",
    "unsubscribe_email": "Unsubscribe from emails",
    "decline_addon": "Decline an add-on",
}

_BANNER_BY_VERDICT: Dict[str, Dict[str, str]] = {
    "no_dark_patterns_found": {"level": "clean", "heading": "No dark patterns found"},
    "inconclusive": {"level": "warn", "heading": "Inconclusive"},
    "dark_patterns_present": {"level": "danger", "heading": "Dark patterns detected"},
}

_MAX_PHRASE_CHARS = 40


def _region_label(region_id: str) -> str:
    return _REGION_LABELS.get(region_id, region_id.replace("_", " "))


def _goal_label(goal: Optional[str]) -> Optional[str]:
    if not goal:
        return None
    return _GOAL_LABELS.get(goal, goal.replace("_", " ").capitalize())


# Delimiter-based, not \b-based: real episode ids in this project use
# underscores on BOTH sides ("episode_auralis_cancel_on_v2"), and Python's
# \b treats "_" as a word character -- so "_on_" has no \b transition on
# either side of "on" and a \b-based pattern silently never matches it.
# site_domain values use a hyphen+dot shape instead ("auralis-on.local").
# Both need to work, so match "on"/"off" delimited by -, _, ., or a real
# string boundary on either side, explicitly, rather than relying on \b.
_OFF_PATTERN = re.compile(r"(?:^|[-_.])off(?:$|[-_.])", re.IGNORECASE)
_ON_PATTERN = re.compile(r"(?:^|[-_.])on(?:$|[-_.])", re.IGNORECASE)


def default_compare_label(meta: Dict) -> str:
    """A sensible, presentation-safe column title for report --compare --
    NEVER the raw CLI argument or filesystem path the user typed (a full
    path is exactly the kind of internal detail this view exists to hide,
    and can be long enough to visually overflow a centered heading).

    Auto-detects this project's own ON/OFF demo-site convention (site_id/
    episode_id containing "-on"/"-off" or "_on"/"_off", e.g.
    "auralis-on.local") word-bounded so it doesn't false-positive on an
    unrelated word (e.g. "onboarding"). Falls back to the episode's own
    site or episode_id verbatim -- still short and real, never a path --
    when neither pattern matches, so a non-demo-site comparison still gets
    a legible label instead of guessing a version it can't actually tell."""
    haystack = f"{meta.get('site') or ''} {meta.get('episode_id') or ''}"
    if _OFF_PATTERN.search(haystack):
        return "Honest version (dark patterns off)"
    if _ON_PATTERN.search(haystack):
        return "Manipulative version (dark patterns on)"
    return meta.get("site") or meta.get("episode_id") or "Episode"


def _severity_label(severity: Optional[int]) -> Optional[str]:
    """Rounds a raw 1-5 severity to a band a non-technical reader can act
    on -- the summary view never shows a bare number (see the style
    requirement this module's docstring quotes)."""
    if severity is None:
        return None
    if severity >= 4:
        return "high"
    if severity == 3:
        return "medium"
    return "low"


def _shorten(text: str, max_chars: int = _MAX_PHRASE_CHARS) -> str:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def _join_and(items: List[str]) -> str:
    items = [i for i in items if i]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


# -- reading the raw episode a second, narrower way: per-element text ------
# report_builder.py's filmstrip carries a screenshot per step but not each
# interactive element's own text -- this module needs that to translate a
# selector into a phrase a human would recognize ("the Cancel link"), so
# it re-reads computed_styles_path the same minimal way report_builder.py
# does (duplicated, not imported, since that helper is module-private
# there -- same small-helper-per-module convention already used elsewhere
# in this codebase, e.g. _resolve_episode_json_path).


def _computed_styles_by_step(episode: Dict, episode_dir: str) -> Dict[int, List[Dict]]:
    import json

    by_step: Dict[int, List[Dict]] = {}
    for step in episode.get("steps") or []:
        cs_path = step.get("computed_styles_path")
        elements: List[Dict] = []
        if cs_path:
            full_path = os.path.join(episode_dir, cs_path)
            if os.path.isfile(full_path):
                with open(full_path, "r", encoding="utf-8") as f:
                    elements = json.load(f) or []
        by_step[step["step_id"]] = elements
    return by_step


def _disclosure_text_by_key(episode: Dict) -> Dict[Tuple[Optional[int], str], str]:
    tags = (episode.get("evidence") or {}).get("ui_regions") or []
    return {(tag["step_id"], tag["selector"]): tag["text"] for tag in tags if "text" in tag}


def _asymmetry_pairs_by_step(episode: Dict) -> Dict[int, List[Dict]]:
    by_step: Dict[int, List[Dict]] = {}
    for pair in (episode.get("evidence") or {}).get("visual_asymmetry") or []:
        by_step.setdefault(pair["step_id"], []).append(pair)
    return by_step


def _element_kind(element: Dict) -> str:
    role = (element.get("role") or "").lower()
    if role in ("checkbox", "radio", "button"):
        return role
    tag = (element.get("tag") or "").lower()
    if tag == "a":
        return "link"
    if tag in ("button", "input"):
        return "button"
    return "element"


def _element_phrase(
    step_id: Optional[int],
    selector: Optional[str],
    attribute: str,
    computed_styles_by_step: Dict[int, List[Dict]],
    disclosure_by_key: Dict[Tuple[Optional[int], str], str],
) -> Optional[str]:
    """Translates a (step_id, selector) evidence pointer into a phrase a
    non-technical reader recognizes, reading only text this episode's own
    capture already recorded (an interactive element's own visible text,
    or a disclosure-tagged element's text) -- never inventing a label.

    information_hiding is a deliberate special case: a Stage-2 judge often
    cites an EARLIER element as ABSENCE evidence ("this page mentions the
    price but not the fee") -- quoting that element's own text next to
    "important information hidden" would misrepresent it as the withheld
    thing itself, when it's actually evidence nothing was withheld THERE.
    Only a genuine disclosure-tagged element (the actual withheld text,
    once it appears) is safe to quote for this attribute; anything else
    falls back to the generic, still-true "flagged here" sentence in
    _build_step_flags() instead of naming an unrelated element."""
    if not selector:
        return None
    disclosure_text = disclosure_by_key.get((step_id, selector))
    if disclosure_text:
        return f'the disclosure text "{_shorten(disclosure_text, 70)}"'
    if attribute == "information_hiding":
        return None
    for element in computed_styles_by_step.get(step_id, []) or []:
        if element.get("selector") == selector:
            text = (element.get("text") or "").strip()
            kind = _element_kind(element)
            if text:
                return f'the "{_shorten(text)}" {kind}'
            return f"an unlabeled {kind}"
    return None


def _find_asymmetry_pair(step_id: int, selectors: List[str], asym_pairs_by_step: Dict[int, List[Dict]]) -> Optional[Dict]:
    wanted = {s for s in selectors if s}
    for pair in asym_pairs_by_step.get(step_id, []):
        if {pair.get("positive_selector"), pair.get("negative_selector")} == wanted:
            return pair
    return None


def _asymmetry_sentence(pair: Dict, label: str) -> str:
    """Reads the pair's OWN measured area_ratio/font_size_ratio (already
    computed by signals/visual_asymmetry.py) to decide which side to call
    "smaller" -- a grounded reading of a stored number, not a fabricated
    visual claim. Falls back to a neutral "visually unequal" phrasing
    when neither ratio is decisively one-sided."""
    pos_text = (pair.get("positive_text") or "").strip() or "the other option"
    neg_text = (pair.get("negative_text") or "").strip() or "this option"
    pos_short, neg_short = _shorten(pos_text, 30), _shorten(neg_text, 30)
    ratio = pair.get("area_ratio") or pair.get("font_size_ratio")
    if ratio and ratio > 1.15:
        return f'{label}: "{neg_short}" is noticeably smaller than "{pos_short}".'
    if ratio and ratio < 0.87:
        return f'{label}: "{pos_short}" is noticeably smaller than "{neg_short}".'
    return f'{label}: "{neg_short}" and "{pos_short}" are visually unequal.'


def _add_step_sentence(step_flags: Dict[int, Dict], step_id: int, level: str, text: str, selectors: List[str]) -> None:
    entry = step_flags.setdefault(step_id, {"level": None, "sentences": []})
    if not any(s["text"] == text for s in entry["sentences"]):
        entry["sentences"].append({"text": text, "selectors": [s for s in selectors if s]})
    if level == "fires":
        entry["level"] = "fires"
    elif entry["level"] is None:
        entry["level"] = "unsure"


def _build_step_flags(
    regions: List[Dict],
    computed_styles_by_step: Dict[int, List[Dict]],
    disclosure_by_key: Dict[Tuple[Optional[int], str], str],
    asym_pairs_by_step: Dict[int, List[Dict]],
) -> Dict[int, Dict]:
    step_flags: Dict[int, Dict] = {}

    for region in regions:
        for level, bucket in (("fires", region["attributes_fired"]), ("unsure", region["attributes_unsure"])):
            grouped: Dict[Tuple[Optional[int], str], List[Dict]] = {}
            for entry in bucket:
                grouped.setdefault((entry["step_id"], entry["attribute"]), []).append(entry)

            for (step_id, attribute), entries in grouped.items():
                if step_id is None:
                    continue  # page/flow-level evidence has no single step to anchor a filmstrip card to
                label = ATTRIBUTE_LABELS.get(attribute, attribute)
                selectors = [e["selector"] for e in entries if e.get("selector")]

                sentence_text = None
                if attribute == "asymmetry" and level == "fires" and len(selectors) == 2:
                    pair = _find_asymmetry_pair(step_id, selectors, asym_pairs_by_step)
                    if pair:
                        sentence_text = _asymmetry_sentence(pair, label)

                if sentence_text is None:
                    phrases = [
                        _element_phrase(step_id, sel, attribute, computed_styles_by_step, disclosure_by_key)
                        for sel in selectors
                    ]
                    phrases = [p for p in phrases if p]
                    if phrases:
                        lead = label if level == "fires" else f"Possibly {label[0].lower()}{label[1:]}"
                        sentence_text = f"{lead}: {_join_and(phrases)}."
                    else:
                        sentence_text = (
                            f"{label} flagged here." if level == "fires" else f"Possibly {label[0].lower()}{label[1:]} here."
                        )

                _add_step_sentence(step_flags, step_id, level, sentence_text, selectors)

    return step_flags


def _named_findings(patterns: List[Dict], regions: List[Dict]) -> List[Dict]:
    """One card per coordinator pattern_combination, verbatim pattern_name
    + description (already human-readable prose -- see coordinator_prompt.v1.txt).
    Falls back to summarizing the single strongest region in plain words
    when no coordinator response has been ingested yet (a real, honest
    state -- not something to hide)."""
    if patterns:
        findings = []
        for p in patterns:
            mechanisms = [f"{ATTRIBUTE_LABELS.get(a, a)} ({a})" for a in (p.get("attributes") or [])]
            findings.append({
                "pattern_name": p["pattern_name"],
                "description": p["description"],
                "mechanisms": mechanisms,
            })
        return findings

    if not regions:
        return []

    region = regions[0]  # already sorted strongest-first by episode_output_builder.build_regions
    attrs = sorted({a["attribute"] for a in region["attributes_fired"]})
    if not attrs:
        attrs = sorted({a["attribute"] for a in region["attributes_unsure"]})
    if not attrs:
        return []

    region_label = _region_label(region["ui_region"])
    labels_lower = [ATTRIBUTE_LABELS.get(a, a)[0].lower() + ATTRIBUTE_LABELS.get(a, a)[1:] for a in attrs]
    description = (
        f"The {region_label} showed signs of {_join_and(labels_lower)}, though no single combined "
        f"pattern has been named for it yet."
    )
    return [{
        "pattern_name": f"Findings in the {region_label}",
        "description": description,
        "mechanisms": [f"{ATTRIBUTE_LABELS.get(a, a)} ({a})" for a in attrs],
    }]


def _plain_language_line(overall: Dict, regions: List[Dict]) -> str:
    if overall["verdict"] == "no_dark_patterns_found":
        return "This flow did not show any of the manipulative patterns this tool checks for."

    for region in regions:
        pattern = region.get("likely_pattern")
        if pattern:
            max_severity = max(
                (a["severity"] for a in region["attributes_fired"] if a["severity"] is not None), default=None
            )
            severity_clause = f" ({_severity_label(max_severity)} severity)" if _severity_label(max_severity) else ""
            return f'This {_region_label(region["ui_region"])} uses a "{pattern["name"]}" pattern{severity_clause}.'

    if regions:
        region = regions[0]
        attrs = sorted({a["attribute"] for a in region["attributes_fired"]})
        if not attrs:
            attrs = sorted({a["attribute"] for a in region["attributes_unsure"]})
        if attrs:
            labels = [ATTRIBUTE_LABELS.get(a, a) for a in attrs]
            return f"The {_region_label(region['ui_region'])} shows signs of {_join_and(labels)}."

    return "The evidence collected was not enough to reach a clear verdict."


def _coverage_sentence(overall: Dict) -> str:
    coverage = overall["coverage"]
    missing = [*coverage["not_assessable"], *coverage["stubbed_pending_stage2"]]
    total = len(coverage["assessed"]) + len(missing)
    sentence = f"{len(coverage['assessed'])} of {total} mechanisms assessed."
    if missing:
        labels = [ATTRIBUTE_LABELS.get(a, a) for a in missing]
        if len(labels) == 1:
            sentence += f" {labels[0]} requires additional data and was not assessed."
        else:
            sentence += f" {_join_and(labels)} require additional data and were not assessed."
    return sentence


def _format_date(episode: Dict) -> Optional[str]:
    steps = sorted(episode.get("steps") or [], key=lambda s: s["step_id"])
    if not steps:
        return None
    timestamp = steps[0].get("timestamp")
    if not timestamp:
        return None
    try:
        dt = datetime.fromisoformat(timestamp)
    except ValueError:
        return None
    return f"{dt.strftime('%B')} {dt.day}, {dt.year}"


def build_summary_data(episode: Dict, episode_dir: str) -> Dict:
    """The single data structure journey/report_summary_html.py renders --
    every field already in plain language, no selector/JSON/attribute-code
    reaches the renderer except inside a `selectors` list explicitly meant
    for a hover tooltip (see _add_step_sentence)."""
    report_data = build_report_data(episode, episode_dir)
    overall = report_data["overall"]
    regions = report_data["regions"]
    filmstrip = report_data["filmstrip"]
    episode_meta = report_data["episode"]
    outcome = report_data["outcome"]

    if overall is None:
        overall = {
            "verdict": "inconclusive",
            "coverage": {"assessed": [], "not_assessable": [], "stubbed_pending_stage2": []},
            "summary": "No computed output yet -- run build-output.",
        }

    patterns = coordinator_pattern_combinations(episode)
    computed_styles_by_step = _computed_styles_by_step(episode, episode_dir)
    disclosure_by_key = _disclosure_text_by_key(episode)
    asym_pairs_by_step = _asymmetry_pairs_by_step(episode)
    step_flags = _build_step_flags(regions, computed_styles_by_step, disclosure_by_key, asym_pairs_by_step)

    banner = dict(_BANNER_BY_VERDICT.get(overall["verdict"], {"level": "warn", "heading": overall["verdict"]}))
    banner["plain_language"] = _plain_language_line(overall, regions)

    findings = _named_findings(patterns, regions)
    if not findings:
        findings_empty_message = (
            "No manipulative patterns were found in this flow."
            if overall["verdict"] == "no_dark_patterns_found"
            else "The evidence collected was inconclusive; no specific pattern could be identified."
        )
    else:
        findings_empty_message = None

    goal_achieved = outcome.get("goal_achieved")
    steps = []
    for step in filmstrip:
        flag = step_flags.get(step["step_id"])
        steps.append({
            "step_id": step["step_id"],
            "screenshot_b64": step["screenshot_b64"],
            "capture_error": step["capture_error"],
            "flagged": flag is not None,
            "flag_level": flag["level"] if flag else None,
            "sentences": flag["sentences"] if flag else [],
        })

    return {
        "meta": {
            "episode_id": episode_meta.get("episode_id"),
            "site": episode_meta.get("site_domain") or episode_meta.get("site_id"),
            "goal_label": _goal_label(episode_meta.get("goal")),
            "date": _format_date(episode),
            "goal_achieved_label": None if goal_achieved is None else ("Achieved" if goal_achieved else "Abandoned"),
        },
        "banner": banner,
        "findings": findings,
        "findings_empty_message": findings_empty_message,
        "coverage_sentence": _coverage_sentence(overall),
        "steps": steps,
    }


def load_summary_data(episode_path: str) -> Dict:
    """CLI-facing convenience: resolve+load an episode.json path the same
    way report.py's build_episode_report() does, then build_summary_data()."""
    from recorder.interactive_v2 import EPISODE_FILENAME

    episode_json_path = episode_path if os.path.isfile(episode_path) else os.path.join(episode_path, EPISODE_FILENAME)
    episode_dir = os.path.dirname(episode_json_path)
    episode = load_episode(episode_json_path)
    return build_summary_data(episode, episode_dir)
