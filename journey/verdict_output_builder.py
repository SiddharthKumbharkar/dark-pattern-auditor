"""Shared, reusable verdict-assembly helpers (Layer 2) -- authoritative-
verdict selection, coverage computation, and >=2-attribute region
co-occurrence grouping, all computed FROM the stored verdict objects,
never hand-authored. These are load-bearing for THREE independent
call sites, not just presentation:
  - llm/payload_builder.py uses compute_region_groups() to build the
    coordinator's evidence_summary.json grounding data.
  - journey/mechanism_verdict_ingest.py uses compute_region_groups()
    (via select_authoritative_verdicts()) to REJECT an ingested
    coordinator response whose pattern_combinations invent attributes
    that weren't actually computed as co-occurring in a region.
  - journey/episode_output_builder.py (the final {overall, regions,
    verdicts} document builder) reuses select_authoritative_verdicts()
    and compute_coverage() directly -- its own `regions` view is a
    broader, single-attribute-inclusive grouping that compute_region_groups()
    deliberately does not replace (region_groups requires >=2 co-occurring
    attributes; it exists specifically to ground the coordinator's
    pattern-naming, a narrower and different question than "what did we
    find anywhere on this page").

See journey/verdict_reconciliation.py for the (different) code-vs-LLM
side-by-side comparison this module does not replace.

Pure functions of an already-loaded episode dict -- no file I/O here.

Authoritative verdict per attribute: a Stage-2 LLM verdict manually
ingested for that attribute (episode.mechanism_verdict.entries,
role="attribute") REPLACES the code agent's own episode.attributes.results
entry -- this is the only place in the pipeline that picks one side over
the other (journey/verdict_reconciliation.py deliberately shows both
side by side instead). This is exactly how the three Stage-2-only stub
attributes (covertness, information_hiding, disparate_treatment) are
meant to ever leave not_assessable: nothing about picking the LLM verdict
when one exists is new detection logic, it's the intended Stage-1-to-
Stage-2 handoff the stubs' own docstrings describe.
"""

from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from attribute_agents.base import ATTRIBUTES, STAGE2_STUB_REASON
from config.ui_regions import UNCLASSIFIED_REGION

# >=3 of 7 attributes not assessed (not_assessable + stubbed_pending_stage2
# combined) is "too many to responsibly call this episode either clean or
# problematic" -- shared by journey/episode_output_builder.py's coverage_limited.
COVERAGE_LIMITED_THRESHOLD = 3
_MIN_ATTRIBUTES_FOR_COMBINATION = 2


def _find_llm_attribute_entries(episode: Dict) -> Dict[str, Dict]:
    entries = (episode.get("mechanism_verdict") or {}).get("entries") or []
    by_attribute = {}
    for entry in entries:
        if entry["role"] == "attribute" and entry["attribute"] is not None:
            by_attribute[entry["attribute"]] = entry
    return by_attribute


def _find_coordinator_entry(episode: Dict) -> Optional[Dict]:
    entries = (episode.get("mechanism_verdict") or {}).get("entries") or []
    matches = [e for e in entries if e["role"] == "coordinator"]
    return matches[-1] if matches else None


def _find_code_result(episode: Dict, attribute: str) -> Optional[Dict]:
    results = (episode.get("attributes") or {}).get("results") or []
    matches = [r for r in results if r["attribute"] == attribute and r["agent_type"] == "code"]
    return matches[0] if matches else None


def _llm_entry_to_verdict(entry: Dict) -> Dict:
    """Mechanically attaches agent_version/agent_type to a Stage-2 raw
    response the same way attribute_agents/base.py mechanically attaches
    them to a code agent's partial result -- an ingested LLM response
    never carries these itself (see llm/payload_builder.py's
    _attribute_response_schema docstring)."""
    response = entry["raw_response"]
    verdict = {
        "attribute": response["attribute"],
        "verdict": response["verdict"],
        "severity": response["severity"],
        "confidence": response["confidence"],
        "evidence_pointers": response["evidence_pointers"],
        "reasoning": response["reasoning"],
        "agent_version": f"llm:{entry['model_name']}/{entry['prompt_version']}",
        "agent_type": "llm",
    }
    if "visual_claim_unverified" in response:
        verdict["visual_claim_unverified"] = response["visual_claim_unverified"]
    return verdict


def select_authoritative_verdicts(episode: Dict) -> List[Dict]:
    """One verdict per attribute, in attribute_agents.base.ATTRIBUTES
    order -- the ingested Stage-2 LLM entry when one exists, else the code
    agent's own result, else (nothing has run yet) a bare not_assessable
    placeholder so callers never have to special-case a missing attribute."""
    llm_entries = _find_llm_attribute_entries(episode)
    verdicts = []
    for attribute in ATTRIBUTES:
        llm_entry = llm_entries.get(attribute)
        if llm_entry is not None:
            verdicts.append(_llm_entry_to_verdict(llm_entry))
            continue
        code_result = _find_code_result(episode, attribute)
        if code_result is not None:
            verdicts.append(code_result)
            continue
        verdicts.append({
            "attribute": attribute, "verdict": "not_assessable", "severity": None, "confidence": 0.0,
            "evidence_pointers": [], "reasoning": "run-attributes has not run yet for this episode.",
            "agent_version": "none", "agent_type": "code",
        })
    return verdicts


def _is_stubbed_pending_stage2(verdict: Dict) -> bool:
    return (
        verdict["verdict"] == "not_assessable"
        and verdict["agent_type"] == "code"
        and verdict["reasoning"] == STAGE2_STUB_REASON
    )


def compute_coverage(verdicts: List[Dict]) -> Dict:
    assessed = [v["attribute"] for v in verdicts if v["verdict"] in ("fires", "no", "unsure")]
    stubbed = [v["attribute"] for v in verdicts if v["verdict"] == "not_assessable" and _is_stubbed_pending_stage2(v)]
    not_assessable = [
        v["attribute"] for v in verdicts
        if v["verdict"] == "not_assessable" and v["attribute"] not in stubbed
    ]
    counts = {
        "fires": sum(1 for v in verdicts if v["verdict"] == "fires"),
        "no": sum(1 for v in verdicts if v["verdict"] == "no"),
        "unsure": sum(1 for v in verdicts if v["verdict"] == "unsure"),
        "not_assessable": len(not_assessable) + len(stubbed),
    }
    return {
        "assessed": assessed,
        "not_assessable": not_assessable,
        "stubbed_pending_stage2": stubbed,
        "counts": counts,
    }


def is_coverage_limited(coverage: Dict) -> bool:
    unassessed = len(coverage["not_assessable"]) + len(coverage["stubbed_pending_stage2"])
    return unassessed >= COVERAGE_LIMITED_THRESHOLD


def _pointer_key(pointer: Dict) -> Optional[Tuple[Optional[int], str]]:
    if not pointer.get("selector"):
        return None
    return (pointer.get("step_id"), pointer["selector"])


def compute_region_groups(verdicts: List[Dict]) -> Dict:
    """Groups attributes that fired/were unsure BY ui_region -- a pattern
    is a combination of attributes on the SAME region, not merely
    co-present on the page. Element-level match (same selector) is the
    strongest signal; region-level co-occurrence (same region, different
    elements) is strong; page-level co-occurrence alone (no shared region
    at all) is weak -- reflected here by three distinct output shapes
    rather than one flat list a consumer would have to re-derive strength
    from."""
    active = [v for v in verdicts if v["verdict"] in ("fires", "unsure")]

    attrs_by_region: Dict[str, set] = defaultdict(set)
    attrs_by_element: Dict[Tuple[str, Optional[int], str], set] = defaultdict(set)
    for v in active:
        for pointer in v["evidence_pointers"]:
            region = pointer.get("ui_region", UNCLASSIFIED_REGION)
            attrs_by_region[region].add(v["attribute"])
            key = _pointer_key(pointer)
            if key is not None:
                attrs_by_element[(region, key[0], key[1])].add(v["attribute"])

    region_groups = []
    for region, attrs in sorted(attrs_by_region.items()):
        if region == "unclassified" or len(attrs) < _MIN_ATTRIBUTES_FOR_COMBINATION:
            continue
        element_matches = [
            {"step_id": step_id, "selector": selector, "attributes": sorted(element_attrs)}
            for (element_region, step_id, selector), element_attrs in attrs_by_element.items()
            if element_region == region and len(element_attrs) >= _MIN_ATTRIBUTES_FOR_COMBINATION
        ]
        strength = "element" if element_matches else "region"
        region_groups.append({
            "ui_region": region,
            "attributes": sorted(attrs),
            "strength": strength,
            "element_matches": sorted(element_matches, key=lambda m: (m["step_id"] or 0, m["selector"])),
        })

    grouped_attribute_sets = {tuple(g["attributes"]) for g in region_groups}
    page_level_attrs = sorted({v["attribute"] for v in active})
    page_level_co_occurrence = (
        page_level_attrs
        if len(page_level_attrs) >= _MIN_ATTRIBUTES_FOR_COMBINATION and tuple(page_level_attrs) not in grouped_attribute_sets
        else []
    )

    return {
        "region_groups": sorted(region_groups, key=lambda g: (g["strength"] != "element", g["ui_region"])),
        "page_level_co_occurrence": page_level_co_occurrence,
    }


def coordinator_pattern_combinations(episode: Dict) -> List[Dict]:
    """The most recently ingested coordinator entry's raw pattern_combinations,
    verbatim -- empty until a coordinator response has been ingested.
    Reused by journey/episode_output_builder.py to ground `likely_pattern`
    per region; never re-derived or reworded here."""
    entry = _find_coordinator_entry(episode)
    if entry is None:
        return []
    return entry["raw_response"].get("pattern_combinations") or []
