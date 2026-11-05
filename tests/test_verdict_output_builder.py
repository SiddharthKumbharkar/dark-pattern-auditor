"""journey/verdict_output_builder.py -- the shared, reusable helpers
(authoritative-verdict selection, coverage, >=2-attribute region
co-occurrence grouping) that llm/payload_builder.py and
journey/mechanism_verdict_ingest.py depend on directly, independent of
the final output document journey/episode_output_builder.py builds --
see tests/test_episode_output_builder.py for that."""

import pytest

from attribute_agents.base import ATTRIBUTES, STAGE2_STUB_REASON
from journey.verdict_output_builder import (
    compute_coverage,
    compute_region_groups,
    coordinator_pattern_combinations,
    is_coverage_limited,
    select_authoritative_verdicts,
)


def _verdict(attribute, verdict, severity=None, confidence=0.7, evidence_pointers=None, reasoning="x", agent_type="code"):
    return {
        "attribute": attribute, "verdict": verdict, "severity": severity, "confidence": confidence,
        "evidence_pointers": evidence_pointers or [], "reasoning": reasoning,
        "agent_version": "test/1.0.0", "agent_type": agent_type,
    }


def _pointer(step_id, selector, region, signal="test.signal"):
    return {"step_id": step_id, "selector": selector, "ui_region": region, "signal": signal}


def _code_result(attribute, **kwargs):
    return _verdict(attribute, agent_type="code", **kwargs)


def _episode_with_results(results, mechanism_verdict=None):
    return {
        "attributes": {"results": results},
        "mechanism_verdict": mechanism_verdict or {},
    }


# -- authoritative verdict selection --------------------------------------


def test_llm_ingested_entry_overrides_code_result_for_that_attribute():
    code_results = [_code_result(a, verdict="not_assessable", reasoning=STAGE2_STUB_REASON) for a in ATTRIBUTES]
    episode = _episode_with_results(code_results, mechanism_verdict={
        "entries": [{
            "role": "attribute", "attribute": "covertness", "model_name": "test-model",
            "prompt_version": "attribute_prompt.v1", "ingested_at": "t", "operator": "op",
            "raw_response": {
                "attribute": "covertness", "verdict": "fires", "severity": 3, "confidence": 0.8,
                "evidence_pointers": [_pointer(1, "#x", "cancellation_flow")],
                "reasoning": "measured contradiction",
            },
        }],
    })
    verdicts = select_authoritative_verdicts(episode)
    covertness = next(v for v in verdicts if v["attribute"] == "covertness")
    assert covertness["verdict"] == "fires"
    assert covertness["agent_type"] == "llm"
    assert covertness["agent_version"] == "llm:test-model/attribute_prompt.v1"


def test_missing_code_result_and_no_llm_entry_defaults_to_not_assessable():
    episode = _episode_with_results([])
    verdicts = select_authoritative_verdicts(episode)
    assert all(v["verdict"] == "not_assessable" for v in verdicts)
    assert {v["attribute"] for v in verdicts} == set(ATTRIBUTES)


# -- coverage computation ---------------------------------------------------


def test_coverage_separates_genuine_not_assessable_from_stubbed_pending_stage2():
    results = [_code_result(a, verdict="no") for a in ("asymmetry", "deception", "complexity", "restriction")]
    results.append(_code_result("covertness", verdict="not_assessable", reasoning=STAGE2_STUB_REASON))
    results.append(_code_result("information_hiding", verdict="not_assessable", reasoning=STAGE2_STUB_REASON))
    results.append(_code_result("disparate_treatment", verdict="not_assessable", reasoning="no paired episode -- genuinely can't assess"))
    verdicts = select_authoritative_verdicts(_episode_with_results(results))
    coverage = compute_coverage(verdicts)

    assert set(coverage["stubbed_pending_stage2"]) == {"covertness", "information_hiding"}
    assert coverage["not_assessable"] == ["disparate_treatment"]
    assert set(coverage["assessed"]) == {"asymmetry", "deception", "complexity", "restriction"}
    assert coverage["counts"] == {"fires": 0, "no": 4, "unsure": 0, "not_assessable": 3}


def test_coverage_limited_true_at_3_of_7_unassessed():
    results = [_code_result(a, verdict="no") for a in ("asymmetry", "deception", "complexity", "restriction")]
    for a in ("covertness", "information_hiding", "disparate_treatment"):
        results.append(_code_result(a, verdict="not_assessable", reasoning=STAGE2_STUB_REASON))
    verdicts = select_authoritative_verdicts(_episode_with_results(results))
    coverage = compute_coverage(verdicts)
    assert is_coverage_limited(coverage) is True


def test_coverage_not_limited_below_threshold():
    results = [_code_result(a, verdict="no") for a in ("asymmetry", "deception", "complexity", "restriction", "disparate_treatment")]
    for a in ("covertness", "information_hiding"):
        results.append(_code_result(a, verdict="not_assessable", reasoning=STAGE2_STUB_REASON))
    verdicts = select_authoritative_verdicts(_episode_with_results(results))
    coverage = compute_coverage(verdicts)
    assert is_coverage_limited(coverage) is False


# -- coordinator pattern_combinations passthrough --------------------------


def test_coordinator_pattern_combinations_empty_when_no_coordinator_entry():
    assert coordinator_pattern_combinations(_episode_with_results([])) == []


def test_coordinator_pattern_combinations_returns_most_recent_entry():
    episode = _episode_with_results([], mechanism_verdict={
        "entries": [
            {
                "role": "coordinator", "attribute": None, "model_name": "m", "prompt_version": "v",
                "ingested_at": "t1", "operator": "op",
                "raw_response": {"pattern_combinations": [{"ui_region": "cancellation_flow", "attributes": ["asymmetry", "deception"], "pattern_name": "old", "description": "d"}]},
            },
            {
                "role": "coordinator", "attribute": None, "model_name": "m", "prompt_version": "v",
                "ingested_at": "t2", "operator": "op",
                "raw_response": {"pattern_combinations": [{"ui_region": "cancellation_flow", "attributes": ["asymmetry", "deception"], "pattern_name": "new", "description": "d"}]},
            },
        ],
    })
    combos = coordinator_pattern_combinations(episode)
    assert [c["pattern_name"] for c in combos] == ["new"]


# -- region grouping: element > region > page strength -----------


def test_element_level_strength_when_two_attributes_share_the_same_selector():
    verdicts = [
        _verdict("asymmetry", "fires", severity=3, evidence_pointers=[_pointer(4, "#cancel-link", "cancellation_flow")]),
        _verdict("deception", "fires", severity=4, evidence_pointers=[_pointer(4, "#cancel-link", "cancellation_flow")]),
    ]
    grouping = compute_region_groups(verdicts)
    assert len(grouping["region_groups"]) == 1
    group = grouping["region_groups"][0]
    assert group["ui_region"] == "cancellation_flow"
    assert set(group["attributes"]) == {"asymmetry", "deception"}
    assert group["strength"] == "element"
    assert group["element_matches"][0]["selector"] == "#cancel-link"


def test_region_level_strength_when_same_region_different_selectors():
    verdicts = [
        _verdict("asymmetry", "fires", severity=3, evidence_pointers=[_pointer(4, "#a", "cancellation_flow")]),
        _verdict("deception", "fires", severity=4, evidence_pointers=[_pointer(5, "#b", "cancellation_flow")]),
    ]
    grouping = compute_region_groups(verdicts)
    assert len(grouping["region_groups"]) == 1
    assert grouping["region_groups"][0]["strength"] == "region"
    assert grouping["region_groups"][0]["element_matches"] == []


def test_page_level_co_occurrence_when_no_shared_region():
    verdicts = [
        _verdict("asymmetry", "fires", severity=3, evidence_pointers=[_pointer(1, "#a", "cancellation_flow")]),
        _verdict("complexity", "fires", severity=2, evidence_pointers=[_pointer(2, "#b", "account_settings")]),
    ]
    grouping = compute_region_groups(verdicts)
    assert grouping["region_groups"] == []
    assert set(grouping["page_level_co_occurrence"]) == {"asymmetry", "complexity"}


def test_single_attribute_in_a_region_is_not_a_combination():
    verdicts = [_verdict("asymmetry", "fires", severity=3, evidence_pointers=[_pointer(1, "#a", "cancellation_flow")])]
    grouping = compute_region_groups(verdicts)
    assert grouping["region_groups"] == []
    assert grouping["page_level_co_occurrence"] == []  # only one attribute active at all


def test_unclassified_region_never_forms_a_named_combination():
    verdicts = [
        _verdict("asymmetry", "fires", severity=3, evidence_pointers=[_pointer(1, None, "unclassified")]),
        _verdict("deception", "fires", severity=4, evidence_pointers=[_pointer(None, None, "unclassified")]),
    ]
    grouping = compute_region_groups(verdicts)
    assert grouping["region_groups"] == []
    # still surfaced as weak, page-level co-occurrence rather than silently dropped
    assert set(grouping["page_level_co_occurrence"]) == {"asymmetry", "deception"}
