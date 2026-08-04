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

likely_pattern gating: the coordinator's pattern_combinations response has
no confidence field to threshold on (an earlier session deliberately
removed finding-level confidence from the judge prompt), so likely_pattern
is gated on the region's own finding_strength instead (never populated for
a "weak" region) rather than a fabricated confidence number --
likely_pattern.confidence is always null here, honestly reflecting that
nothing upstream produced one.
"""

from collections import defaultdict
from typing import Dict, List, Optional

from attribute_agents.base import ATTRIBUTES
from config.ui_regions import UNCLASSIFIED_REGION
from journey.verdict_output_builder import (
    compute_coverage,
    coordinator_pattern_combinations,
    is_coverage_limited,
    select_authoritative_verdicts,
)

BUILDER_VERSION = "episode_output_builder/1.0.0"

_HIGH_SEVERITY_THRESHOLD = 4
_STRONG_FIRED_COUNT = 3
_STRONG_SEVERITY_5_FIRED_COUNT = 2
_MODERATE_FIRED_COUNT = 2

_STRENGTH_RANK = {"strong": 0, "moderate": 1, "weak": 2}


def _region_of(pointer: Dict) -> str:
    return pointer.get("ui_region") or UNCLASSIFIED_REGION


def _finding_strength(fired_here: List[Dict]) -> str:
    """fired_here: verdict objects (verdict=="fires") whose evidence
    touches this region. Deliberately never counts unsure attributes --
    an unsure-only region is "weak", same as a single fired attribute,
    never stronger (per spec: "unsure-only regions are also weak")."""
    n = len(fired_here)
    if n >= _STRONG_FIRED_COUNT:
        return "strong"
    if n >= _STRONG_SEVERITY_5_FIRED_COUNT and any(v["severity"] == 5 for v in fired_here):
        return "strong"
    if n == _MODERATE_FIRED_COUNT:
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


def _assessment_sentence(region: str, fired_here: List[Dict], unsure_here: List[Dict], finding_strength: str) -> str:
    parts = []
    if fired_here:
        clauses = ", ".join(f"{v['attribute']} (severity {v['severity']})" for v in fired_here)
        parts.append(f"{len(fired_here)} attribute(s) fired in {region}: {clauses}")
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

        finding_strength = _finding_strength(fired_here)
        active_attributes = {v["attribute"] for v in (fired_here + unsure_here)}

        regions.append({
            "ui_region": region,
            "representative_element": _representative_element(fired_here, unsure_here, region),
            "steps": _steps_for_region(verdicts_here, region),
            "attributes_fired": [
                {"attribute": v["attribute"], "severity": v["severity"], "confidence": v["confidence"]}
                for v in sorted(fired_here, key=lambda v: v["severity"] or 0, reverse=True)
            ],
            "attributes_unsure": sorted(v["attribute"] for v in unsure_here),
            "attributes_absent": absent,
            "attributes_not_assessed": not_assessed,
            "likely_pattern": _likely_pattern(region, active_attributes, patterns, finding_strength),
            "finding_strength": finding_strength,
            "assessment": _assessment_sentence(region, fired_here, unsure_here, finding_strength),
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


def _summary_sentence(verdict: str, coverage: Dict, coverage_limited: bool, regions: List[Dict]) -> str:
    sentences = []
    if coverage_limited:
        unassessed = len(coverage["not_assessable"]) + len(coverage["stubbed_pending_stage2"])
        sentences.append(
            f"Coverage is limited: only {len(coverage['assessed'])} of {len(ATTRIBUTES)} attributes were "
            f"assessed ({unassessed} not assessed), so this verdict should be treated as preliminary."
        )

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
    human_review_recommended = (
        coverage_limited
        or any(v["verdict"] == "unsure" for v in verdicts)
        or any(
            v["verdict"] == "fires" and v["severity"] is not None and v["severity"] >= _HIGH_SEVERITY_THRESHOLD
            for v in verdicts
        )
    )
    return {
        "verdict": verdict,
        "coverage_limited": coverage_limited,
        "human_review_recommended": human_review_recommended,
        "coverage": coverage,
        "regions_summary": _regions_summary(episode, regions),
        "summary": _summary_sentence(verdict, coverage, coverage_limited, regions),
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
