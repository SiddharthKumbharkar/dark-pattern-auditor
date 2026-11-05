"""journey/episode_output_builder.py -- the final {overall, regions,
verdicts} document builder. Everything here is derived from a flat
verdicts list; these tests exercise region inclusion/exclusion,
finding_strength thresholds, likely_pattern gating, overall.verdict
computation, coverage_limited flagging, and regions_summary counts,
plus schema conformance of the assembled document."""

from attribute_agents.base import ATTRIBUTES, STAGE2_STUB_REASON
from journey.episode_output_builder import build_episode_output, build_overall, build_regions
from journey.schema_migration import validate_computed_output


def _verdict(attribute, verdict, severity=None, confidence=0.7, evidence_pointers=None, reasoning="x", agent_type="code"):
    return {
        "attribute": attribute, "verdict": verdict, "severity": severity, "confidence": confidence,
        "evidence_pointers": evidence_pointers or [], "reasoning": reasoning,
        "agent_version": "test/1.0.0", "agent_type": agent_type,
    }


def _pointer(step_id, selector, region, signal="test.signal"):
    return {"step_id": step_id, "selector": selector, "ui_region": region, "signal": signal}


def _all_no_results(exclude=()):
    return [_verdict(a, "no") for a in ATTRIBUTES if a not in exclude]


def _episode(results, mechanism_verdict=None, ui_regions=None, claim_extraction=None):
    return {
        "attributes": {"results": results},
        "mechanism_verdict": mechanism_verdict or {},
        "evidence": {"ui_regions": ui_regions or [], "claim_extraction": claim_extraction or []},
    }


def _claim(claim_text, claim_type, step_id, selector="div.timer"):
    return {"claim_text": claim_text, "claim_type": claim_type, "step_id": step_id, "selector": selector, "normalized_value": None}


def _coordinator_mv(patterns):
    return {"entries": [{
        "role": "coordinator", "attribute": None, "model_name": "m", "prompt_version": "v",
        "ingested_at": "t", "operator": "op", "raw_response": {"pattern_combinations": patterns},
    }]}


# -- region inclusion filter -------------------------------------------------


def test_region_with_only_no_and_not_assessable_is_excluded():
    results = _all_no_results()
    verdicts = [_verdict(a, "no") for a in ATTRIBUTES]
    regions = build_regions(verdicts, [])
    assert regions == []


def test_region_with_one_fired_attribute_is_included():
    results = _all_no_results(exclude=("asymmetry",))
    results.append(_verdict("asymmetry", "fires", severity=3, evidence_pointers=[_pointer(1, "#a", "cancellation_flow")]))
    verdicts = results
    regions = build_regions(verdicts, [])
    assert len(regions) == 1
    assert regions[0]["ui_region"] == "cancellation_flow"


def test_region_with_only_unsure_is_included():
    verdicts = _all_no_results(exclude=("restriction",))
    verdicts.append(_verdict("restriction", "unsure", evidence_pointers=[_pointer(2, "#b", "checkout_price_summary")]))
    regions = build_regions(verdicts, [])
    assert len(regions) == 1
    assert regions[0]["attributes_unsure"] == [{"attribute": "restriction", "step_id": 2, "selector": "#b"}]
    assert regions[0]["attributes_fired"] == []


def test_unclassified_region_included_when_something_fires_there():
    verdicts = _all_no_results(exclude=("complexity",))
    verdicts.append(_verdict("complexity", "fires", severity=2, evidence_pointers=[_pointer(1, None, "unclassified")]))
    regions = build_regions(verdicts, [])
    assert len(regions) == 1
    assert regions[0]["ui_region"] == "unclassified"


# -- finding_strength thresholds --------------------------------------------


def test_finding_strength_weak_for_exactly_one_fired():
    verdicts = _all_no_results(exclude=("asymmetry",))
    verdicts.append(_verdict("asymmetry", "fires", severity=3, evidence_pointers=[_pointer(1, "#a", "signup_form")]))
    regions = build_regions(verdicts, [])
    assert regions[0]["finding_strength"] == "weak"


def test_finding_strength_weak_for_unsure_only():
    verdicts = _all_no_results(exclude=("asymmetry",))
    verdicts.append(_verdict("asymmetry", "unsure", evidence_pointers=[_pointer(1, "#a", "signup_form")]))
    regions = build_regions(verdicts, [])
    assert regions[0]["finding_strength"] == "weak"


def test_finding_strength_moderate_for_exactly_two_fired():
    verdicts = _all_no_results(exclude=("asymmetry", "deception"))
    verdicts.append(_verdict("asymmetry", "fires", severity=2, evidence_pointers=[_pointer(1, "#a", "signup_form")]))
    verdicts.append(_verdict("deception", "fires", severity=3, evidence_pointers=[_pointer(1, "#b", "signup_form")]))
    regions = build_regions(verdicts, [])
    assert regions[0]["finding_strength"] == "moderate"


def test_finding_strength_strong_for_three_or_more_fired():
    verdicts = _all_no_results(exclude=("asymmetry", "deception", "complexity"))
    for a in ("asymmetry", "deception", "complexity"):
        verdicts.append(_verdict(a, "fires", severity=2, evidence_pointers=[_pointer(1, f"#{a}", "signup_form")]))
    regions = build_regions(verdicts, [])
    assert regions[0]["finding_strength"] == "strong"


def test_finding_strength_strong_for_two_fired_when_one_is_severity_5():
    verdicts = _all_no_results(exclude=("asymmetry", "deception"))
    verdicts.append(_verdict("asymmetry", "fires", severity=5, evidence_pointers=[_pointer(1, "#a", "signup_form")]))
    verdicts.append(_verdict("deception", "fires", severity=2, evidence_pointers=[_pointer(1, "#b", "signup_form")]))
    regions = build_regions(verdicts, [])
    assert regions[0]["finding_strength"] == "strong"


def test_finding_strength_moderate_not_strong_for_two_fired_without_severity_5():
    verdicts = _all_no_results(exclude=("asymmetry", "deception"))
    verdicts.append(_verdict("asymmetry", "fires", severity=4, evidence_pointers=[_pointer(1, "#a", "signup_form")]))
    verdicts.append(_verdict("deception", "fires", severity=3, evidence_pointers=[_pointer(1, "#b", "signup_form")]))
    regions = build_regions(verdicts, [])
    assert regions[0]["finding_strength"] == "moderate"


# -- per-attribute location (step_id/selector) -------------------------------


def test_attributes_fired_entries_carry_their_own_step_id_and_selector():
    verdicts = _all_no_results(exclude=("asymmetry",))
    verdicts.append(_verdict("asymmetry", "fires", severity=3, evidence_pointers=[_pointer(4, "#cancel", "cancellation_flow")]))
    regions = build_regions(verdicts, [])
    assert regions[0]["attributes_fired"][0]["step_id"] == 4
    assert regions[0]["attributes_fired"][0]["selector"] == "#cancel"


def test_attributes_fired_location_is_null_for_group_level_evidence_with_no_selector():
    verdicts = _all_no_results(exclude=("deception",))
    verdicts.append(_verdict("deception", "fires", severity=3, evidence_pointers=[_pointer(6, None, "unclassified")]))
    regions = build_regions(verdicts, [])
    entry = regions[0]["attributes_fired"][0]
    assert entry["step_id"] == 6
    assert entry["selector"] is None


def test_attributes_fired_location_is_fully_null_when_evidence_has_no_step_id_either():
    verdicts = _all_no_results(exclude=("restriction",))
    verdicts.append(_verdict("restriction", "fires", severity=3, evidence_pointers=[_pointer(None, None, "unclassified")]))
    regions = build_regions(verdicts, [])
    entry = regions[0]["attributes_fired"][0]
    assert entry["step_id"] is None
    assert entry["selector"] is None


# -- a verdict's evidence spanning multiple locations in one region ----------
# (regression coverage for the under-reporting bug: a verdict that fired on
# multiple pairs/elements within one region was previously collapsed down to
# its single FIRST evidence pointer in attributes_fired, and scored as a
# lone/"weak" fire regardless of how much evidence it actually carried.)


def test_attributes_fired_carries_one_entry_per_distinct_location_not_just_the_first():
    verdicts = _all_no_results(exclude=("asymmetry",))
    verdicts.append(_verdict("asymmetry", "fires", severity=3, evidence_pointers=[
        _pointer(4, "#keep", "cancellation_flow"), _pointer(4, "#cancel", "cancellation_flow"),
        _pointer(5, "#keep", "cancellation_flow"), _pointer(5, "#cancel", "cancellation_flow"),
    ]))
    regions = build_regions(verdicts, [])
    locations = {(a["step_id"], a["selector"]) for a in regions[0]["attributes_fired"]}
    assert locations == {(4, "#keep"), (4, "#cancel"), (5, "#keep"), (5, "#cancel")}
    assert all(a["attribute"] == "asymmetry" for a in regions[0]["attributes_fired"])
    assert regions[0]["steps"] == [4, 5]


def test_attributes_unsure_also_carries_one_entry_per_distinct_location():
    verdicts = _all_no_results(exclude=("restriction",))
    verdicts.append(_verdict("restriction", "unsure", evidence_pointers=[
        _pointer(4, "#a", "checkout_price_summary"), _pointer(5, "#b", "checkout_price_summary"),
    ]))
    regions = build_regions(verdicts, [])
    locations = {(a["step_id"], a["selector"]) for a in regions[0]["attributes_unsure"]}
    assert locations == {(4, "#a"), (5, "#b")}


def test_finding_strength_strong_for_a_single_attribute_firing_across_enough_distinct_locations():
    # Same fixture as the discrimination-run bug report: one attribute
    # (asymmetry), 2 pairs, both buttons of each, across 2 steps -- 4
    # distinct locations. A single-verdict region like this used to be
    # scored "weak" (n=1 distinct attribute); breadth of evidence must be
    # able to reach "strong" on its own, same threshold as 3 distinct
    # attributes converging.
    verdicts = _all_no_results(exclude=("asymmetry",))
    verdicts.append(_verdict("asymmetry", "fires", severity=3, evidence_pointers=[
        _pointer(4, "#keep", "cancellation_flow"), _pointer(4, "#cancel", "cancellation_flow"),
        _pointer(5, "#keep", "cancellation_flow"), _pointer(5, "#cancel", "cancellation_flow"),
    ]))
    regions = build_regions(verdicts, [])
    assert regions[0]["finding_strength"] == "strong"


def test_finding_strength_moderate_for_a_single_attribute_firing_at_exactly_two_distinct_locations():
    verdicts = _all_no_results(exclude=("asymmetry",))
    verdicts.append(_verdict("asymmetry", "fires", severity=3, evidence_pointers=[
        _pointer(4, "#cancel", "cancellation_flow"), _pointer(5, "#cancel", "cancellation_flow"),
    ]))
    regions = build_regions(verdicts, [])
    assert regions[0]["finding_strength"] == "moderate"


def test_finding_strength_still_weak_for_a_single_attribute_at_a_single_location():
    # Unchanged baseline case: breadth of 1 does not get upgraded.
    verdicts = _all_no_results(exclude=("asymmetry",))
    verdicts.append(_verdict("asymmetry", "fires", severity=3, evidence_pointers=[_pointer(4, "#cancel", "cancellation_flow")]))
    regions = build_regions(verdicts, [])
    assert regions[0]["finding_strength"] == "weak"


# -- shared_elements: >=2 fired attributes on the EXACT SAME element ---------


def test_shared_element_detected_when_two_attributes_fire_on_the_same_selector():
    verdicts = _all_no_results(exclude=("asymmetry", "deception"))
    verdicts.append(_verdict("asymmetry", "fires", severity=3, evidence_pointers=[_pointer(4, "#cancel", "cancellation_flow")]))
    verdicts.append(_verdict("deception", "fires", severity=2, evidence_pointers=[_pointer(4, "#cancel", "cancellation_flow")]))
    regions = build_regions(verdicts, [])
    assert regions[0]["shared_elements"] == [{"step_id": 4, "selector": "#cancel", "attributes": ["asymmetry", "deception"]}]


def test_shared_element_forces_strong_even_with_only_two_low_severity_fires():
    # Neither the ">=3 fired" nor the "severity==5" strong rules apply here
    # (2 fired, max severity 2) -- the shared element alone must be enough.
    verdicts = _all_no_results(exclude=("asymmetry", "deception"))
    verdicts.append(_verdict("asymmetry", "fires", severity=2, evidence_pointers=[_pointer(4, "#cancel", "cancellation_flow")]))
    verdicts.append(_verdict("deception", "fires", severity=2, evidence_pointers=[_pointer(4, "#cancel", "cancellation_flow")]))
    regions = build_regions(verdicts, [])
    assert regions[0]["finding_strength"] == "strong"


def test_no_shared_element_when_attributes_fire_on_different_selectors():
    verdicts = _all_no_results(exclude=("asymmetry", "deception"))
    verdicts.append(_verdict("asymmetry", "fires", severity=2, evidence_pointers=[_pointer(4, "#a", "cancellation_flow")]))
    verdicts.append(_verdict("deception", "fires", severity=2, evidence_pointers=[_pointer(4, "#b", "cancellation_flow")]))
    regions = build_regions(verdicts, [])
    assert regions[0]["shared_elements"] == []
    assert regions[0]["finding_strength"] == "moderate"  # falls back to the plain 2-fired rule


def test_shared_element_requires_two_distinct_attributes_not_two_pointers_from_one():
    verdicts = _all_no_results(exclude=("asymmetry",))
    verdicts.append(_verdict("asymmetry", "fires", severity=3, evidence_pointers=[
        _pointer(4, "#cancel", "cancellation_flow"), _pointer(5, "#cancel", "cancellation_flow"),
    ]))
    regions = build_regions(verdicts, [])
    assert regions[0]["shared_elements"] == []


def test_shared_element_ignores_unsure_attributes_only_counts_fires():
    verdicts = _all_no_results(exclude=("asymmetry", "restriction"))
    verdicts.append(_verdict("asymmetry", "fires", severity=3, evidence_pointers=[_pointer(4, "#cancel", "cancellation_flow")]))
    verdicts.append(_verdict("restriction", "unsure", evidence_pointers=[_pointer(4, "#cancel", "cancellation_flow")]))
    regions = build_regions(verdicts, [])
    assert regions[0]["shared_elements"] == []


# -- likely_pattern gating ----------------------------------------------------


def test_likely_pattern_null_on_weak_region_even_with_matching_coordinator_pattern():
    verdicts = _all_no_results(exclude=("asymmetry",))
    verdicts.append(_verdict("asymmetry", "fires", severity=3, evidence_pointers=[_pointer(1, "#a", "cancellation_flow")]))
    patterns = [{"ui_region": "cancellation_flow", "attributes": ["asymmetry"], "pattern_name": "x", "description": "d"}]
    regions = build_regions(verdicts, patterns)
    assert regions[0]["finding_strength"] == "weak"
    assert regions[0]["likely_pattern"] is None


def test_likely_pattern_populated_on_moderate_region_with_matching_coordinator_pattern():
    verdicts = _all_no_results(exclude=("asymmetry", "deception"))
    verdicts.append(_verdict("asymmetry", "fires", severity=3, evidence_pointers=[_pointer(1, "#a", "cancellation_flow")]))
    verdicts.append(_verdict("deception", "fires", severity=3, evidence_pointers=[_pointer(1, "#b", "cancellation_flow")]))
    patterns = [{"ui_region": "cancellation_flow", "attributes": ["asymmetry", "deception"], "pattern_name": "confirmshaming_retention_trap", "description": "d"}]
    regions = build_regions(verdicts, patterns)
    assert regions[0]["finding_strength"] == "moderate"
    assert regions[0]["likely_pattern"] == {"name": "confirmshaming_retention_trap", "confidence": None, "source": "coordinator"}


def test_likely_pattern_null_when_coordinator_pattern_names_a_different_region():
    verdicts = _all_no_results(exclude=("asymmetry", "deception"))
    verdicts.append(_verdict("asymmetry", "fires", severity=3, evidence_pointers=[_pointer(1, "#a", "cancellation_flow")]))
    verdicts.append(_verdict("deception", "fires", severity=3, evidence_pointers=[_pointer(1, "#b", "cancellation_flow")]))
    patterns = [{"ui_region": "checkout_price_summary", "attributes": ["asymmetry", "deception"], "pattern_name": "x", "description": "d"}]
    regions = build_regions(verdicts, patterns)
    assert regions[0]["likely_pattern"] is None


def test_likely_pattern_null_when_coordinator_pattern_invents_an_attribute_not_active_here():
    verdicts = _all_no_results(exclude=("asymmetry", "deception"))
    verdicts.append(_verdict("asymmetry", "fires", severity=3, evidence_pointers=[_pointer(1, "#a", "cancellation_flow")]))
    verdicts.append(_verdict("deception", "fires", severity=3, evidence_pointers=[_pointer(1, "#b", "cancellation_flow")]))
    patterns = [{"ui_region": "cancellation_flow", "attributes": ["asymmetry", "complexity"], "pattern_name": "x", "description": "d"}]
    regions = build_regions(verdicts, patterns)
    assert regions[0]["likely_pattern"] is None


# -- attributes_absent / attributes_not_assessed / representative_element / steps --


def test_attributes_absent_and_not_assessed_are_global_context_not_region_filtered():
    verdicts = [_verdict(a, "no") for a in ("deception", "complexity", "restriction")]
    verdicts.append(_verdict("asymmetry", "fires", severity=3, evidence_pointers=[_pointer(1, "#a", "cancellation_flow")]))
    for a in ("covertness", "information_hiding", "disparate_treatment"):
        verdicts.append(_verdict(a, "not_assessable", reasoning=STAGE2_STUB_REASON))
    regions = build_regions(verdicts, [])
    assert set(regions[0]["attributes_absent"]) == {"deception", "complexity", "restriction"}
    assert set(regions[0]["attributes_not_assessed"]) == {"covertness", "information_hiding", "disparate_treatment"}


def test_representative_element_is_the_highest_severity_fired_selector():
    verdicts = _all_no_results(exclude=("asymmetry", "deception"))
    verdicts.append(_verdict("asymmetry", "fires", severity=2, evidence_pointers=[_pointer(1, "#low", "cancellation_flow")]))
    verdicts.append(_verdict("deception", "fires", severity=5, evidence_pointers=[_pointer(1, "#high", "cancellation_flow")]))
    regions = build_regions(verdicts, [])
    assert regions[0]["representative_element"] == "#high"


def test_steps_are_sorted_and_unique_from_the_regions_own_pointers():
    verdicts = _all_no_results(exclude=("asymmetry",))
    verdicts.append(_verdict("asymmetry", "fires", severity=3, evidence_pointers=[
        _pointer(3, "#a", "cancellation_flow"), _pointer(1, "#b", "cancellation_flow"), _pointer(1, "#b", "cancellation_flow"),
    ]))
    regions = build_regions(verdicts, [])
    assert regions[0]["steps"] == [1, 3]


# -- overall.verdict computation --------------------------------------------


def test_overall_verdict_no_dark_patterns_found_when_all_clean():
    verdicts = [_verdict(a, "no") for a in ATTRIBUTES]
    regions = build_regions(verdicts, [])
    episode = _episode([])
    overall = build_overall(episode, verdicts, regions)
    assert regions == []
    assert overall["verdict"] == "no_dark_patterns_found"


def test_overall_verdict_dark_patterns_present_when_a_strong_region_exists():
    verdicts = _all_no_results(exclude=("asymmetry", "deception", "complexity"))
    for a in ("asymmetry", "deception", "complexity"):
        verdicts.append(_verdict(a, "fires", severity=3, evidence_pointers=[_pointer(1, f"#{a}", "cancellation_flow")]))
    regions = build_regions(verdicts, [])
    overall = build_overall(_episode([]), verdicts, regions)
    assert overall["verdict"] == "dark_patterns_present"


def test_overall_verdict_dark_patterns_present_when_a_moderate_region_exists():
    verdicts = _all_no_results(exclude=("asymmetry", "deception"))
    for a in ("asymmetry", "deception"):
        verdicts.append(_verdict(a, "fires", severity=3, evidence_pointers=[_pointer(1, f"#{a}", "cancellation_flow")]))
    regions = build_regions(verdicts, [])
    overall = build_overall(_episode([]), verdicts, regions)
    assert overall["verdict"] == "dark_patterns_present"


def test_overall_verdict_inconclusive_when_only_weak_findings_exist():
    verdicts = _all_no_results(exclude=("asymmetry",))
    verdicts.append(_verdict("asymmetry", "fires", severity=3, evidence_pointers=[_pointer(1, "#a", "cancellation_flow")]))
    regions = build_regions(verdicts, [])
    overall = build_overall(_episode([]), verdicts, regions)
    assert overall["verdict"] == "inconclusive"


def test_overall_verdict_inconclusive_when_only_unsure_exists():
    verdicts = _all_no_results(exclude=("restriction",))
    verdicts.append(_verdict("restriction", "unsure", evidence_pointers=[_pointer(1, "#a", "cancellation_flow")]))
    regions = build_regions(verdicts, [])
    overall = build_overall(_episode([]), verdicts, regions)
    assert overall["verdict"] == "inconclusive"


# -- coverage_limited / human_review_recommended -----------------------------


def test_coverage_limited_true_flows_through_to_overall():
    verdicts = _all_no_results(exclude=("covertness", "information_hiding", "disparate_treatment"))
    for a in ("covertness", "information_hiding", "disparate_treatment"):
        verdicts.append(_verdict(a, "not_assessable", reasoning=STAGE2_STUB_REASON))
    regions = build_regions(verdicts, [])
    overall = build_overall(_episode([]), verdicts, regions)
    assert overall["coverage_limited"] is True
    assert overall["human_review_recommended"] is True
    assert overall["summary"].startswith("Human review needed")
    assert "limited coverage" in overall["summary"]
    # the terse summary never repeats the X-of-7/Y-not-assessed breakdown --
    # that detail lives in overall.coverage / the Coverage table's per-attribute reasoning
    assert "of 7" not in overall["summary"]
    assert "not assessed" not in overall["summary"]


def test_coverage_not_limited_below_threshold():
    verdicts = _all_no_results(exclude=("covertness", "information_hiding"))
    for a in ("covertness", "information_hiding"):
        verdicts.append(_verdict(a, "not_assessable", reasoning=STAGE2_STUB_REASON))
    regions = build_regions(verdicts, [])
    overall = build_overall(_episode([]), verdicts, regions)
    assert overall["coverage_limited"] is False


def test_human_review_recommended_for_high_severity_fires_even_with_good_coverage():
    verdicts = _all_no_results(exclude=("asymmetry",))
    verdicts.append(_verdict("asymmetry", "fires", severity=4, evidence_pointers=[_pointer(1, "#a", "cancellation_flow")]))
    regions = build_regions(verdicts, [])
    overall = build_overall(_episode([]), verdicts, regions)
    assert overall["coverage_limited"] is False
    assert overall["human_review_recommended"] is True


# -- urgency_claims: no attribute agent judges these, so surface + flag ------


def test_urgency_claim_detected_and_deduplicated_with_all_its_step_ids():
    verdicts = [_verdict(a, "no") for a in ATTRIBUTES]
    claims = [
        _claim("Sale ends in:", "urgency_phrase", 1, selector="#timer"),
        _claim("Sale ends in:", "urgency_phrase", 2, selector="#timer"),
        _claim("Sale ends in:", "urgency_phrase", 3, selector="#timer"),
    ]
    episode = _episode([], claim_extraction=claims)
    regions = build_regions(verdicts, [])
    overall = build_overall(episode, verdicts, regions)
    assert overall["urgency_claims"] == [
        {"claim_text": "Sale ends in:", "claim_type": "urgency_phrase", "selector": "#timer", "step_ids": [1, 2, 3]}
    ]


def test_urgency_claim_forces_human_review_even_with_good_coverage_and_no_findings():
    verdicts = [_verdict(a, "no") for a in ATTRIBUTES]
    claims = [_claim("Hurry", "urgency_phrase", 1)]
    episode = _episode([], claim_extraction=claims)
    regions = build_regions(verdicts, [])
    overall = build_overall(episode, verdicts, regions)
    assert overall["coverage_limited"] is False
    assert overall["human_review_recommended"] is True
    assert "urgency/countdown claim" in overall["summary"]


def test_no_urgency_claims_leaves_human_review_recommended_false_when_otherwise_clean():
    verdicts = [_verdict(a, "no") for a in ATTRIBUTES]
    episode = _episode([], claim_extraction=[])
    regions = build_regions(verdicts, [])
    overall = build_overall(episode, verdicts, regions)
    assert overall["urgency_claims"] == []
    assert overall["human_review_recommended"] is False


def test_non_urgency_claim_types_are_excluded():
    verdicts = [_verdict(a, "no") for a in ATTRIBUTES]
    claims = [
        _claim("Best seller", "social_proof", 1),
        _claim("Low stock - 1 item left", "stock_count", 1),
        _claim("32 people viewing", "viewer_count", 1),
    ]
    episode = _episode([], claim_extraction=claims)
    regions = build_regions(verdicts, [])
    overall = build_overall(episode, verdicts, regions)
    assert overall["urgency_claims"] == []
    assert overall["human_review_recommended"] is False


def test_urgency_claims_at_different_selectors_are_not_merged():
    verdicts = [_verdict(a, "no") for a in ATTRIBUTES]
    claims = [
        _claim("Hurry", "urgency_phrase", 1, selector="#top-banner"),
        _claim("Hurry", "urgency_phrase", 1, selector="#product-widget"),
    ]
    episode = _episode([], claim_extraction=claims)
    regions = build_regions(verdicts, [])
    overall = build_overall(episode, verdicts, regions)
    assert len(overall["urgency_claims"]) == 2


def test_summary_stays_terse_even_with_a_long_claim_text_which_stays_full_in_the_data():
    # A regex can match a short urgent phrase inside a much longer text
    # node (e.g. a whole marketing paragraph) -- the terse one-line
    # summary never quotes claim text at all (that detail lives in the
    # HTML report's dedicated urgency-claims callout), but the full text
    # is still preserved, untouched, in overall.urgency_claims itself.
    long_text = "Hurry, this offer is only valid for the next 24 hours so act now before it's gone forever and ever!"
    verdicts = [_verdict(a, "no") for a in ATTRIBUTES]
    episode = _episode([], claim_extraction=[_claim(long_text, "urgency_phrase", 1)])
    regions = build_regions(verdicts, [])
    overall = build_overall(episode, verdicts, regions)
    assert overall["urgency_claims"][0]["claim_text"] == long_text  # untouched in the data
    assert long_text not in overall["summary"]
    assert overall["summary"] == "Human review needed — urgency/countdown claims found. No dark patterns found."


# -- regions_summary: clean regions counted, never listed --------------------


def test_regions_summary_counts_clean_regions_without_listing_them():
    verdicts = _all_no_results(exclude=("asymmetry",))
    verdicts.append(_verdict("asymmetry", "fires", severity=3, evidence_pointers=[_pointer(1, "#a", "cancellation_flow")]))
    regions = build_regions(verdicts, [])
    ui_regions_tags = [
        {"step_id": 1, "selector": "#a", "region": "cancellation_flow"},
        {"step_id": 2, "selector": "#b", "region": "login_form"},
        {"step_id": 3, "selector": "#c", "region": "account_settings"},
        {"step_id": 4, "selector": "#d", "region": "cookie_consent_banner"},
    ]
    episode = _episode([], ui_regions=ui_regions_tags)
    overall = build_overall(episode, verdicts, regions)
    summary = overall["regions_summary"]
    assert summary["total_regions_examined"] == 4
    assert summary["regions_with_findings"] == 1
    assert summary["regions_clean"] == 3
    # the 3 clean regions are counted, never enumerated anywhere in the region objects themselves
    assert {r["ui_region"] for r in regions} == {"cancellation_flow"}


def test_regions_summary_zero_examined_zero_findings_for_a_fully_clean_episode():
    verdicts = [_verdict(a, "no") for a in ATTRIBUTES]
    regions = build_regions(verdicts, [])
    episode = _episode([], ui_regions=[])
    overall = build_overall(episode, verdicts, regions)
    assert overall["regions_summary"] == {"total_regions_examined": 0, "regions_with_findings": 0, "regions_clean": 0}


# -- full document assembly / schema conformance -----------------------------


def _episode_with_code_results(results, mechanism_verdict=None, ui_regions=None, claim_extraction=None):
    return _episode(results, mechanism_verdict, ui_regions, claim_extraction)


def test_clean_episode_produces_exactly_empty_regions_and_no_dark_patterns_found():
    """The demo-suite success case (patterns OFF): regions == [], not null
    or a missing field; overall.verdict == "no_dark_patterns_found"."""
    results = [_verdict(a, "no") for a in ATTRIBUTES]
    episode = _episode_with_code_results(results, ui_regions=[
        {"step_id": 1, "selector": "#x", "region": "cancellation_flow"},
    ])
    output = build_episode_output(episode)
    assert output["regions"] == []
    assert output["overall"]["verdict"] == "no_dark_patterns_found"
    assert output["overall"]["regions_summary"]["regions_with_findings"] == 0
    errors = validate_computed_output(output)
    assert errors == [], errors


def test_full_output_conforms_to_computed_output_schema_with_findings():
    results = [_verdict(a, "no") for a in ("deception", "restriction")]
    results.append(_verdict("asymmetry", "fires", severity=5, evidence_pointers=[_pointer(4, "#x", "cancellation_flow")]))
    results.append(_verdict("complexity", "fires", severity=3, evidence_pointers=[_pointer(4, "#y", "cancellation_flow")]))
    for a in ("covertness", "information_hiding", "disparate_treatment"):
        results.append(_verdict(a, "not_assessable", reasoning=STAGE2_STUB_REASON))
    mechanism_verdict = _coordinator_mv([
        {"ui_region": "cancellation_flow", "attributes": ["asymmetry", "complexity"], "pattern_name": "confirmshaming_retention_trap", "description": "d"},
    ])
    episode = _episode_with_code_results(
        results, mechanism_verdict=mechanism_verdict,
        ui_regions=[
            {"step_id": 4, "selector": "#x", "region": "cancellation_flow"},
            {"step_id": 4, "selector": "#y", "region": "cancellation_flow"},
            {"step_id": 2, "selector": "#z", "region": "login_form"},
        ],
        claim_extraction=[_claim("Offer ends soon", "deadline_phrase", 1)],
    )
    output = build_episode_output(episode)
    errors = validate_computed_output(output)
    assert errors == [], errors
    assert output["overall"]["verdict"] == "dark_patterns_present"
    assert output["regions"][0]["likely_pattern"]["name"] == "confirmshaming_retention_trap"
    assert output["overall"]["urgency_claims"] == [
        {"claim_text": "Offer ends soon", "claim_type": "deadline_phrase", "selector": "div.timer", "step_ids": [1]}
    ]
