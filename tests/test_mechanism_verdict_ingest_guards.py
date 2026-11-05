"""Fast, isolated unit tests for the new ingest-time guards (Issues 2+4) --
plain dicts, no recording/browser fixture, unlike the e2e
tests/test_mechanism_verdict_ingest.py. Covers: ui_region provenance
(an ingested response can't invent a region), and the visual-claim guard
on both --role attribute and --role coordinator responses.
"""

from journey.mechanism_verdict_ingest import (
    coerce_untagged_evidence_pointer_regions,
    validate_evidence_pointer_regions,
    validate_pattern_combinations_grounded,
    validate_visual_claims_attribute,
    validate_visual_claims_coordinator,
)

REGION_MAP = {(4, "#cancel-link"): "cancellation_flow", (5, "#keep-btn"): "cancellation_flow"}


# -- ui_region provenance (Issue 2): a response can't invent a region ------


def test_matching_ui_region_passes():
    response = {"evidence_pointers": [{"step_id": 4, "selector": "#cancel-link", "ui_region": "cancellation_flow", "signal": "x"}]}
    assert validate_evidence_pointer_regions(response, REGION_MAP) == []


def test_invented_ui_region_is_rejected():
    response = {"evidence_pointers": [{"step_id": 4, "selector": "#cancel-link", "ui_region": "checkout_price_summary", "signal": "x"}]}
    errors = validate_evidence_pointer_regions(response, REGION_MAP)
    assert len(errors) == 1
    assert "does not match" in errors[0]


def test_unknown_selector_must_claim_unclassified():
    response = {"evidence_pointers": [{"step_id": 1, "selector": "#never-tagged", "ui_region": "signup_form", "signal": "x"}]}
    errors = validate_evidence_pointer_regions(response, REGION_MAP)
    assert len(errors) == 1
    assert "unclassified" in errors[0]

    ok_response = {"evidence_pointers": [{"step_id": 1, "selector": "#never-tagged", "ui_region": "unclassified", "signal": "x"}]}
    assert validate_evidence_pointer_regions(ok_response, REGION_MAP) == []


def test_null_selector_must_claim_unclassified():
    response = {"evidence_pointers": [{"step_id": None, "selector": None, "ui_region": "unclassified", "signal": "group.signal"}]}
    assert validate_evidence_pointer_regions(response, REGION_MAP) == []


def test_response_with_no_evidence_pointers_field_is_fine():
    assert validate_evidence_pointer_regions({"summary": "x"}, REGION_MAP) == []


# -- coercion backstop: untagged elements get "unclassified", not rejected -


def test_coerce_fixes_an_invented_region_on_a_never_tagged_selector():
    # Same shape as test_unknown_selector_must_claim_unclassified, but run
    # through the coercion step first -- the invented label is fixed up
    # in place instead of surviving to fail validation.
    response = {"evidence_pointers": [{"step_id": 1, "selector": "#never-tagged", "ui_region": "signup_form", "signal": "x"}]}
    log = coerce_untagged_evidence_pointer_regions(response, REGION_MAP)
    assert len(log) == 1
    assert "signup_form" in log[0] and "unclassified" in log[0]
    assert response["evidence_pointers"][0]["ui_region"] == "unclassified"
    # and now validation passes, since the label matches region_map's
    # (absent-key) expectation of "unclassified"
    assert validate_evidence_pointer_regions(response, REGION_MAP) == []


def test_coerce_leaves_a_genuinely_tagged_mismatch_alone():
    # (4, "#cancel-link") IS in REGION_MAP as "cancellation_flow" -- a
    # model claiming a DIFFERENT region for a REAL tagged element is a
    # genuine grounding error, not an absent-tag artifact, so coercion
    # must not touch it; validate_evidence_pointer_regions() still rejects.
    response = {"evidence_pointers": [{"step_id": 4, "selector": "#cancel-link", "ui_region": "checkout_price_summary", "signal": "x"}]}
    log = coerce_untagged_evidence_pointer_regions(response, REGION_MAP)
    assert log == []
    assert response["evidence_pointers"][0]["ui_region"] == "checkout_price_summary"  # unchanged
    errors = validate_evidence_pointer_regions(response, REGION_MAP)
    assert len(errors) == 1


def test_coerce_does_not_touch_an_already_correct_pointer():
    response = {"evidence_pointers": [{"step_id": 4, "selector": "#cancel-link", "ui_region": "cancellation_flow", "signal": "x"}]}
    log = coerce_untagged_evidence_pointer_regions(response, REGION_MAP)
    assert log == []
    assert response["evidence_pointers"][0]["ui_region"] == "cancellation_flow"


def test_coerce_does_not_touch_an_already_correctly_unclassified_pointer():
    response = {"evidence_pointers": [{"step_id": 1, "selector": "#never-tagged", "ui_region": "unclassified", "signal": "x"}]}
    log = coerce_untagged_evidence_pointer_regions(response, REGION_MAP)
    assert log == []


def test_coerce_handles_multiple_pointers_independently():
    response = {
        "evidence_pointers": [
            {"step_id": 1, "selector": "#never-tagged", "ui_region": "signup_form", "signal": "a"},
            {"step_id": 4, "selector": "#cancel-link", "ui_region": "cancellation_flow", "signal": "b"},
            {"step_id": 99, "selector": "#also-never-tagged", "ui_region": "retention_offer", "signal": "c"},
        ]
    }
    log = coerce_untagged_evidence_pointer_regions(response, REGION_MAP)
    assert len(log) == 2  # only the two untagged, wrongly-labeled pointers
    regions = [p["ui_region"] for p in response["evidence_pointers"]]
    assert regions == ["unclassified", "cancellation_flow", "unclassified"]


def test_coerce_response_with_no_evidence_pointers_field_is_fine():
    assert coerce_untagged_evidence_pointer_regions({"summary": "x"}, REGION_MAP) == []


# -- visual-claim guard, --role attribute (Issue 4) ------------------------


def test_no_visual_language_passes_regardless_of_grounding():
    response = {"reasoning": "contrast_ratio=1.2, below the 3.0 threshold.", "evidence_pointers": []}
    assert validate_visual_claims_attribute(response, screenshots_supplied=True) == []
    assert validate_visual_claims_attribute(response, screenshots_supplied=False) == []


def test_visual_claim_with_no_screenshots_supplied_is_always_rejected():
    response = {"reasoning": "The screenshot shows the link is clearly legible.", "evidence_pointers": []}
    errors = validate_visual_claims_attribute(response, screenshots_supplied=False)
    assert len(errors) == 1
    assert "zero screenshots" in errors[0]


def test_visual_claim_with_screenshots_but_no_grounding_is_rejected():
    response = {
        "reasoning": "The screenshot shows the link is clearly legible against the background.",
        "evidence_pointers": [{"step_id": 4, "selector": "#x", "ui_region": "unclassified", "signal": "visual_asymmetry.contrast_ratio"}],
    }
    errors = validate_visual_claims_attribute(response, screenshots_supplied=True)
    assert len(errors) == 1
    assert "not grounded" not in errors[0]  # message wording check below is the real assertion
    assert "no evidence_pointers entry is image-sourced" in errors[0]


def test_visual_claim_grounded_by_image_sourced_pointer_is_accepted():
    response = {
        "reasoning": "The screenshot shows the link is clearly legible against the background.",
        "evidence_pointers": [
            {"step_id": 4, "selector": "#x", "ui_region": "unclassified", "signal": "screenshot_visual_inspection.legibility"},
        ],
    }
    assert validate_visual_claims_attribute(response, screenshots_supplied=True) == []


def test_visual_claim_grounded_by_explicit_flag_is_accepted():
    response = {
        "reasoning": "The screenshot shows the link is clearly legible against the background.",
        "evidence_pointers": [],
        "visual_claim_unverified": True,
    }
    assert validate_visual_claims_attribute(response, screenshots_supplied=True) == []


def test_visual_claim_flag_set_false_is_not_grounding():
    response = {
        "reasoning": "You can see the button is much larger than the link next to it.",
        "evidence_pointers": [],
        "visual_claim_unverified": False,
    }
    errors = validate_visual_claims_attribute(response, screenshots_supplied=True)
    assert len(errors) == 1


# -- visual-claim guard, --role coordinator (Issue 4) -----------------------


def test_coordinator_visual_claim_without_flag_is_rejected():
    response = {"pattern_combinations": [
        {"ui_region": "cancellation_flow", "attributes": ["asymmetry", "deception"],
         "pattern_name": "x", "description": "You can see the keep button visually dominates the page."},
    ]}
    errors = validate_visual_claims_coordinator(response)
    assert len(errors) == 1
    assert "pattern_combinations[0]" in errors[0]


def test_coordinator_visual_claim_with_flag_is_accepted():
    response = {"pattern_combinations": [
        {"ui_region": "cancellation_flow", "attributes": ["asymmetry", "deception"],
         "pattern_name": "x", "description": "You can see the keep button visually dominates the page.",
         "visual_claim_unverified": True},
    ]}
    assert validate_visual_claims_coordinator(response) == []


def test_coordinator_no_visual_language_needs_no_flag():
    response = {"pattern_combinations": [
        {"ui_region": "cancellation_flow", "attributes": ["asymmetry", "deception"],
         "pattern_name": "x", "description": "Both attributes measured contradictions in the same region."},
    ]}
    assert validate_visual_claims_coordinator(response) == []


# -- pattern_combinations must be grounded in code-computed region_groups --


def test_pattern_combination_matching_a_computed_group_passes():
    episode = {
        "attributes": {"results": [
            {"attribute": "asymmetry", "verdict": "fires", "severity": 3, "confidence": 0.8,
             "evidence_pointers": [{"step_id": 4, "selector": "#a", "ui_region": "cancellation_flow", "signal": "x"}],
             "reasoning": "x", "agent_version": "v", "agent_type": "code"},
            {"attribute": "deception", "verdict": "fires", "severity": 4, "confidence": 0.7,
             "evidence_pointers": [{"step_id": 4, "selector": "#a", "ui_region": "cancellation_flow", "signal": "y"}],
             "reasoning": "y", "agent_version": "v", "agent_type": "code"},
        ]},
        "mechanism_verdict": {},
    }
    response = {"pattern_combinations": [
        {"ui_region": "cancellation_flow", "attributes": ["asymmetry", "deception"], "pattern_name": "x", "description": "d"},
    ]}
    assert validate_pattern_combinations_grounded(response, episode) == []


def test_pattern_combination_inventing_an_uncomputed_attribute_is_rejected():
    episode = {
        "attributes": {"results": [
            {"attribute": "asymmetry", "verdict": "fires", "severity": 3, "confidence": 0.8,
             "evidence_pointers": [{"step_id": 4, "selector": "#a", "ui_region": "cancellation_flow", "signal": "x"}],
             "reasoning": "x", "agent_version": "v", "agent_type": "code"},
        ]},
        "mechanism_verdict": {},
    }
    response = {"pattern_combinations": [
        {"ui_region": "cancellation_flow", "attributes": ["asymmetry", "complexity"], "pattern_name": "x", "description": "d"},
    ]}
    errors = validate_pattern_combinations_grounded(response, episode)
    assert len(errors) == 1
    assert "complexity" in errors[0]


def test_empty_pattern_combinations_needs_no_grounding():
    assert validate_pattern_combinations_grounded({"pattern_combinations": []}, {"attributes": {"results": []}, "mechanism_verdict": {}}) == []
