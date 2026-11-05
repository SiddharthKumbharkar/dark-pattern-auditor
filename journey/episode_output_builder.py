"""Builds the final, single {overall, regions, verdicts} output document
for one episode (PRESENTATION layer only) -- every claim here is derived
from the flat `verdicts` list (journey.verdict_output_builder's
select_authoritative_verdicts), never hand-authored. See that module's
docstring for why compute_region_groups() (>=2-attribute co-occurrence,
used to ground the coordinator's prompt and validate its ingested
response) is a deliberately different, narrower question than `regions`
here (any region with >=1 fired/unsure attribute, single-attribute
findings included).

Pure function of an already-loaded episode dict -- no file I/O; build_output.py
(the CLI) reads/writes episode.json and validates the result against
schema/mechanism_verdict.v1.schema.json's ComputedOutput def.

Design choices worth knowing:
  - Severity/confidence stay in `verdicts` and in attributes_fired/
    attributes_unsure (still real data, still drive finding_strength/
    sorting/human_review_recommended) but the human-facing HTML report
    (journey/report_html.py) deliberately never RENDERS them -- the report
    is about what fired and WHERE, not a numeric score.
  - Every fired/unsure attribute carries the (step_id, selector) its
    evidence actually points at within this region, so a person can go
    find the exact element -- not just "asymmetry fired somewhere in
    cancellation_flow". When a verdict's own evidence spans MULTIPLE
    locations in the same region (e.g. asymmetry firing on both buttons
    of 2 separate keep/cancel pairs), attributes_fired/attributes_unsure
    carry one entry per (verdict, location), not one entry total for the
    verdict -- see _locations_for_verdict(). finding_strength's `weight`
    is likewise the max of "how many distinct attributes fired" and "how
    many distinct locations the richest single attribute's own evidence
    touches", so a single attribute firing broadly isn't scored the same
    as one firing narrowly (see _finding_strength()).
  - shared_elements: >=2 attributes firing on the EXACT SAME (step_id,
    selector) is the strongest, most locatable signal this pipeline can
    produce (independent measurements converging on one spot) -- a region
    with a shared element is always "strong", regardless of how many
    OTHER attributes fired elsewhere in the same region.
  - overall.urgency_claims is the one field here NOT derived from
    `verdicts` -- it reads episode.evidence.claim_extraction directly.
    That's a deliberate, narrow exception: no attribute agent judges
    countdown-timer/urgency/deadline claims at all today (a real coverage
    gap -- the 7-attribute framework has no "false urgency" attribute,
    and deception.py only checks cross-revisit timer resets, never a
    single episode's persistent claim). Rather than inventing a
    threshold-based auto-verdict for something this ambiguous (a real
    flash sale also says "ends in"), presence alone is surfaced for a
    human to judge and forces human_review_recommended -- see
    _urgency_claims().
  - likely_pattern gating: the coordinator's pattern_combinations response
    has no confidence field to threshold on (an earlier session
    deliberately removed finding-level confidence from the judge prompt),
    so likely_pattern is gated on the region's own finding_strength
    instead (never populated for a "weak" region) rather than a
    fabricated confidence number -- likely_pattern.confidence is always
    null here, honestly reflecting that nothing upstream produced one.
"""

from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from attribute_agents.base import ATTRIBUTES
from config.ui_regions import UNCLASSIFIED_REGION
from journey.verdict_output_builder import (
    compute_coverage,
    coordinator_pattern_combinations,
    is_coverage_limited,
    select_authoritative_verdicts,
)

BUILDER_VERSION = "episode_output_builder/2.0.0"

_HIGH_SEVERITY_THRESHOLD = 4
_STRONG_FIRED_COUNT = 3
_STRONG_SEVERITY_5_FIRED_COUNT = 2
_MODERATE_FIRED_COUNT = 2
_MIN_ATTRIBUTES_FOR_SHARED_ELEMENT = 2

_STRENGTH_RANK = {"strong": 0, "moderate": 1, "weak": 2}


def _region_of(pointer: Dict) -> str:
    return pointer.get("ui_region") or UNCLASSIFIED_REGION


def _locations_for_verdict(verdict: Dict, region: str) -> List[Dict]:
    """ALL distinct (step_id, selector) locations this verdict's own
    evidence points at within `region` -- not just the first pointer.
    A verdict that fired on multiple pairs/elements (e.g. asymmetry
    firing on both buttons of 2 separate keep/cancel pairs, across 2
    different steps) has to surface every one of those locations here,
    or the findings view silently under-reports evidence that the
    verdict itself actually carries (issue: a region showed only the
    FIRST of 4 evidence_pointers, understating both what fired and
    finding_strength -- see _finding_strength()).

    Falls back to bare step_ids (selector null) for group-level evidence
    with no single element, and to a single (null, null) entry when
    nothing in this verdict's evidence carries a step_id either (fully
    page/flow-level evidence, e.g. a friction-ratio signal) -- never
    invented, only ever what the evidence actually has. Deduplicated and
    sorted for determinism."""
    pointers_here = [p for p in verdict["evidence_pointers"] if _region_of(p) == region]
    with_selector = {(p.get("step_id"), p["selector"]) for p in pointers_here if p.get("selector")}
    if with_selector:
        return [
            {"step_id": step_id, "selector": selector}
            for step_id, selector in sorted(with_selector, key=lambda x: (x[0] if x[0] is not None else -1, x[1]))
        ]
    with_step = {p["step_id"] for p in pointers_here if p.get("step_id") is not None}
    if with_step:
        return [{"step_id": step_id, "selector": None} for step_id in sorted(with_step)]
    return [{"step_id": None, "selector": None}]


def _shared_elements(fired_here: List[Dict], region: str) -> List[Dict]:
    """(step_id, selector) pairs where >=2 DISTINCT fired attributes'
    evidence points at the EXACT SAME element -- independent measurements
    converging on one spot, the strongest and most locatable signal this
    pipeline can produce. Deliberately fired-only (not unsure) -- matches
    "attributes fire on the same element", not "were merely uncertain
    about the same element"."""
    attrs_by_element: Dict[Tuple[Optional[int], str], set] = defaultdict(set)
    for v in fired_here:
        for pointer in v["evidence_pointers"]:
            if _region_of(pointer) != region or not pointer.get("selector"):
                continue
            key = (pointer.get("step_id"), pointer["selector"])
            attrs_by_element[key].add(v["attribute"])

    shared = [
        {"step_id": step_id, "selector": selector, "attributes": sorted(attrs)}
        for (step_id, selector), attrs in attrs_by_element.items()
        if len(attrs) >= _MIN_ATTRIBUTES_FOR_SHARED_ELEMENT
    ]
    return sorted(shared, key=lambda s: (s["step_id"] or 0, s["selector"]))


def _finding_strength(fired_here: List[Dict], shared_elements: List[Dict], region: str) -> str:
    """fired_here: verdict objects (verdict=="fires") whose evidence
    touches this region. A shared element (>=2 attributes, exact same
    spot) is always "strong" regardless of total fired count -- that
    convergence is itself the strong signal. Otherwise deliberately never
    counts unsure attributes -- an unsure-only region is "weak", same as
    a single fired attribute, never stronger.

    `weight` is the max of two counts, not just "how many distinct
    attributes fired": (a) the plain distinct-attribute count (the
    original signal -- several DIFFERENT mechanisms converging on one
    region), and (b) the richest single attribute's own evidence breadth
    within this region (how many distinct (step_id, selector) locations
    its evidence touches, via _locations_for_verdict()). Without (b), an
    attribute that fires broadly -- e.g. asymmetry firing on both buttons
    of 2 separate keep/cancel pairs, across 2 steps, 4 evidence pointers
    -- was scored as n=1 ("weak"), identical to a single, narrow,
    one-pointer fire. A verdict is not "weak" just because only one
    ATTRIBUTE fired, if that attribute's own evidence is itself broad."""
    if shared_elements:
        return "strong"
    n_attributes = len(fired_here)
    max_locations = max((len(_locations_for_verdict(v, region)) for v in fired_here), default=0)
    weight = max(n_attributes, max_locations)
    if weight >= _STRONG_FIRED_COUNT:
        return "strong"
    if n_attributes >= _STRONG_SEVERITY_5_FIRED_COUNT and any(v["severity"] == 5 for v in fired_here):
        return "strong"
    if weight >= _MODERATE_FIRED_COUNT:
        return "moderate"
    return "weak"


def _representative_element(fired_here: List[Dict], unsure_here: List[Dict], region: str) -> Optional[str]:
    """Selector of the highest-severity fired element in this region;
    falls back to the first unsure element's selector when nothing fired
    here, so a weak, unsure-only region still gets something to anchor a
    report thumbnail to."""
    candidates = sorted(fired_here, key=lambda v: v["severity"] or 0, reverse=True) or unsure_here
    for verdict in candidates:
        for pointer in verdict["evidence_pointers"]:
            if _region_of(pointer) == region and pointer.get("selector"):
                return pointer["selector"]
    return None


def _steps_for_region(verdicts_here: List[Dict], region: str) -> List[int]:
    steps = {
        pointer["step_id"]
        for verdict in verdicts_here
        for pointer in verdict["evidence_pointers"]
        if _region_of(pointer) == region and pointer.get("step_id") is not None
    }
    return sorted(steps)


def _likely_pattern(region: str, active_attributes: set, patterns: List[Dict], finding_strength: str) -> Optional[Dict]:
    """Only ever populated for strong/moderate regions -- never off a
    single weak signal. Matches a coordinator pattern_combinations entry
    the same way ingest-time validation does: same ui_region, and the
    pattern's attributes must be a subset of what actually fired/was
    unsure in this region."""
    if finding_strength == "weak":
        return None
    for pattern in patterns:
        if pattern.get("ui_region") != region:
            continue
        attrs = set(pattern.get("attributes") or [])
        if attrs and attrs.issubset(active_attributes):
            return {"name": pattern["pattern_name"], "confidence": None, "source": "coordinator"}
    return None


def _assessment_sentence(
    region: str, fired_here: List[Dict], unsure_here: List[Dict], shared_elements: List[Dict], finding_strength: str
) -> str:
    parts = []
    shared_attrs = {a for s in shared_elements for a in s["attributes"]}
    for s in shared_elements:
        where = f"{s['selector']} (step {s['step_id']})" if s["step_id"] is not None else s["selector"]
        parts.append(f"{', '.join(s['attributes'])} all fired on the same element -- {where}")

    remaining = [v for v in fired_here if v["attribute"] not in shared_attrs]
    if remaining:
        clauses = []
        for v in remaining:
            n_locations = len(_locations_for_verdict(v, region))
            clauses.append(f"{v['attribute']} ({n_locations} locations)" if n_locations > 1 else v["attribute"])
        clause_str = ", ".join(clauses)
        parts.append(f"{clause_str} also fired in {region}" if shared_elements else f"{clause_str} fired in {region}")

    if unsure_here:
        parts.append(f"{', '.join(v['attribute'] for v in unsure_here)} came back unsure")
    if not parts:
        parts.append(f"No confirmed findings in {region}")
    return f"{'; '.join(parts)} -- finding_strength: {finding_strength}."


def build_regions(verdicts: List[Dict], patterns: List[Dict]) -> List[Dict]:
    """Groups the flat verdicts list by ui_region -- a region appears here
    only if at least one attribute fired or was unsure with evidence tied
    to it. Every claim inside a region object traces back to one of
    `verdicts`' own fields; attributes_absent/attributes_not_assessed are
    the same global lists in every region (a "no"/"not_assessable" verdict
    carries no region-tied evidence of its own to filter by -- see
    attribute_agents/base.py's hard rule that only fires/unsure verdicts
    are required to carry evidence_pointers)."""
    verdicts_by_region: Dict[str, List[Dict]] = defaultdict(list)
    for verdict in verdicts:
        regions_touched = {_region_of(p) for p in verdict["evidence_pointers"]}
        for region in regions_touched:
            verdicts_by_region[region].append(verdict)

    absent = sorted(v["attribute"] for v in verdicts if v["verdict"] == "no")
    not_assessed = sorted(v["attribute"] for v in verdicts if v["verdict"] == "not_assessable")

    regions = []
    for region, verdicts_here in verdicts_by_region.items():
        fired_here = [v for v in verdicts_here if v["verdict"] == "fires"]
        unsure_here = [v for v in verdicts_here if v["verdict"] == "unsure"]
        if not fired_here and not unsure_here:
            continue

        shared_elements = _shared_elements(fired_here, region)
        finding_strength = _finding_strength(fired_here, shared_elements, region)
        active_attributes = {v["attribute"] for v in (fired_here + unsure_here)}

        regions.append({
            "ui_region": region,
            "representative_element": _representative_element(fired_here, unsure_here, region),
            "steps": _steps_for_region(verdicts_here, region),
            "shared_elements": shared_elements,
            # One entry per (verdict, location) -- a verdict whose evidence
            # touches N distinct locations in this region produces N
            # entries, not 1, so the findings view can't under-report
            # evidence the verdict itself actually carries.
            "attributes_fired": [
                {"attribute": v["attribute"], "severity": v["severity"], "confidence": v["confidence"], **loc}
                for v in sorted(fired_here, key=lambda v: v["severity"] or 0, reverse=True)
                for loc in _locations_for_verdict(v, region)
            ],
            "attributes_unsure": sorted(
                (
                    {"attribute": v["attribute"], **loc}
                    for v in unsure_here
                    for loc in _locations_for_verdict(v, region)
                ),
                key=lambda x: (x["attribute"], x["step_id"] if x["step_id"] is not None else -1, x["selector"] or ""),
            ),
            "attributes_absent": absent,
            "attributes_not_assessed": not_assessed,
            "likely_pattern": _likely_pattern(region, active_attributes, patterns, finding_strength),
            "finding_strength": finding_strength,
            "assessment": _assessment_sentence(region, fired_here, unsure_here, shared_elements, finding_strength),
        })

    regions.sort(key=lambda r: (
        _STRENGTH_RANK[r["finding_strength"]],
        -(max((a["severity"] for a in r["attributes_fired"]), default=0)),
        r["ui_region"],
    ))
    return regions


def _regions_summary(episode: Dict, regions: List[Dict]) -> Dict:
    """total_regions_examined: every distinct region signals/ui_regions.py
    tagged on ANY captured element this episode, whether or not anything
    fired there -- the false-positive/discrimination signal. Folded with
    the findings regions via union (rather than assumed to be a superset)
    because a group-level, selector-less evidence_pointer defaults to
    "unclassified" independently of the per-element tagger and could in
    principle name a region the element-level pass never happened to tag,
    so regions_clean can never go negative."""
    examined = {tag["region"] for tag in (episode.get("evidence") or {}).get("ui_regions") or []}
    with_findings = {r["ui_region"] for r in regions}
    examined |= with_findings
    return {
        "total_regions_examined": len(examined),
        "regions_with_findings": len(with_findings),
        "regions_clean": len(examined - with_findings),
    }


_URGENCY_CLAIM_TYPES = {"urgency_phrase", "countdown_timer", "deadline_phrase"}


def _urgency_claims(episode: Dict) -> List[Dict]:
    """Countdown-timer/urgency/deadline claims signals/claims.py already
    extracted into episode.evidence.claim_extraction -- no attribute agent
    currently judges these (a real coverage gap: the 7-attribute framework
    has no "false urgency" attribute, and deception.py only checks
    cross-revisit timer resets, never a single episode's persistent
    claim). Rather than inventing a threshold-based auto-verdict for
    something this ambiguous (a real flash sale also says "ends in"),
    presence alone is surfaced here for a human to judge directly --
    deduplicated by (claim_text, selector), with every step_id it
    appeared at, so a human can see at a glance whether it's static
    across the whole episode."""
    claims = (episode.get("evidence") or {}).get("claim_extraction") or []
    by_key: Dict[Tuple[Optional[str], Optional[str]], Dict] = {}
    for claim in claims:
        if claim.get("claim_type") not in _URGENCY_CLAIM_TYPES:
            continue
        key = (claim.get("claim_text"), claim.get("selector"))
        entry = by_key.setdefault(key, {
            "claim_text": claim.get("claim_text"),
            "claim_type": claim.get("claim_type"),
            "selector": claim.get("selector"),
            "step_ids": [],
        })
        if claim.get("step_id") is not None:
            entry["step_ids"].append(claim["step_id"])

    result = list(by_key.values())
    for entry in result:
        entry["step_ids"] = sorted(set(entry["step_ids"]))
    return sorted(result, key=lambda e: (e["claim_type"], e["claim_text"] or ""))


def _overall_verdict(verdicts: List[Dict], regions: List[Dict]) -> str:
    """Computed from confirmed (fires) / unsure findings only, straight off
    `verdicts` (not indirectly off `regions`' non-emptiness) so an
    ingested Stage-2 verdict that happens to carry no region-tied evidence
    still counts."""
    any_fires = any(v["verdict"] == "fires" for v in verdicts)
    any_unsure = any(v["verdict"] == "unsure" for v in verdicts)
    if not any_fires and not any_unsure:
        return "no_dark_patterns_found"
    if any(r["finding_strength"] in ("strong", "moderate") for r in regions):
        return "dark_patterns_present"
    return "inconclusive"


def _review_reasons(coverage_limited: bool, verdicts: List[Dict], urgency_claims: List[Dict]) -> List[str]:
    """Terse, human-facing reasons -- the numbers/explanations behind each
    one are already visible elsewhere in the report (the Coverage table's
    per-attribute reasoning, the urgency-claims callout with full text and
    step links), so the summary sentence itself never repeats them."""
    reasons = []
    if coverage_limited:
        reasons.append("limited coverage")
    if any(v["verdict"] == "unsure" for v in verdicts):
        reasons.append("unsure finding(s)")
    if any(
        v["verdict"] == "fires" and v["severity"] is not None and v["severity"] >= _HIGH_SEVERITY_THRESHOLD
        for v in verdicts
    ):
        reasons.append("high-severity finding(s)")
    if urgency_claims:
        reasons.append("urgency/countdown claims found")
    return reasons


def _summary_sentence(verdict: str, review_reasons: List[str], regions: List[Dict]) -> str:
    sentences = []
    if review_reasons:
        sentences.append(f"Human review needed — {', '.join(review_reasons)}.")

    if verdict == "dark_patterns_present":
        strong_or_moderate = [r for r in regions if r["finding_strength"] in ("strong", "moderate")]
        names = ", ".join(f"{r['ui_region']} ({r['finding_strength']})" for r in strong_or_moderate)
        sentences.append(f"Dark patterns present: {names}.")
    elif verdict == "inconclusive":
        if regions:
            names = ", ".join(r["ui_region"] for r in regions)
            sentences.append(f"Inconclusive: only weak or unsure findings, in {names}.")
        else:
            sentences.append("Inconclusive: an unsure verdict exists with no region-tied evidence.")
    else:
        sentences.append("No dark patterns found.")

    return " ".join(sentences)


def build_overall(episode: Dict, verdicts: List[Dict], regions: List[Dict]) -> Dict:
    coverage = compute_coverage(verdicts)
    coverage_limited = is_coverage_limited(coverage)
    verdict = _overall_verdict(verdicts, regions)
    urgency_claims = _urgency_claims(episode)
    review_reasons = _review_reasons(coverage_limited, verdicts, urgency_claims)
    human_review_recommended = bool(review_reasons)
    return {
        "verdict": verdict,
        "coverage_limited": coverage_limited,
        "human_review_recommended": human_review_recommended,
        "coverage": coverage,
        "regions_summary": _regions_summary(episode, regions),
        "urgency_claims": urgency_claims,
        "summary": _summary_sentence(verdict, review_reasons, regions),
    }


def build_episode_output(episode: Dict) -> Dict:
    """The single, unified {overall, regions, verdicts} document for one
    episode -- exactly the three sections the flat verdicts list can
    honestly support; nothing here is a fourth, hand-authored view."""
    verdicts = select_authoritative_verdicts(episode)
    patterns = coordinator_pattern_combinations(episode)
    regions = build_regions(verdicts, patterns)
    overall = build_overall(episode, verdicts, regions)
    return {"overall": overall, "regions": regions, "verdicts": verdicts}
