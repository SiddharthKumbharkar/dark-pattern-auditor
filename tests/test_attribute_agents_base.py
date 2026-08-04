import pytest

from attribute_agents.base import (
    AttributeAgent,
    ContractViolation,
    no_result,
    not_assessable_result,
    run_agent,
    scale_severity,
)
from journey.baselines import BaselineStore


@pytest.fixture
def baselines():
    return BaselineStore()  # loads the real repo baselines.json


def _agent(assess_fn, required_signals=None, attribute="asymmetry"):
    return AttributeAgent(
        agent_id="test_agent",
        attribute=attribute,
        agent_version="test/1.0.0",
        agent_type="code",
        required_signals=required_signals or [],
        assess=assess_fn,
    )


def test_unknown_attribute_rejected():
    with pytest.raises(ValueError):
        AttributeAgent(
            agent_id="x", attribute="not_a_real_attribute", agent_version="1", agent_type="code",
            required_signals=[], assess=lambda e, g, b: {},
        )


def test_unknown_agent_type_rejected():
    with pytest.raises(ValueError):
        AttributeAgent(
            agent_id="x", attribute="asymmetry", agent_version="1", agent_type="statistical",
            required_signals=[], assess=lambda e, g, b: {},
        )


# -- hard rule: empty evidence_pointers + fires/unsure -> downgrade to "no" --


def test_fires_with_empty_evidence_is_downgraded_to_no(baselines):
    agent = _agent(lambda e, g, b: {
        "verdict": "fires", "severity": 4, "confidence": 0.9, "evidence_pointers": [], "reasoning": "bug: no evidence attached",
    })
    result, warnings = run_agent(agent, {}, None, baselines)
    assert result["verdict"] == "no"
    assert result["severity"] is None
    assert len(warnings) == 1
    assert "downgraded" in warnings[0]


def test_unsure_with_empty_evidence_is_downgraded_to_no(baselines):
    agent = _agent(lambda e, g, b: {
        "verdict": "unsure", "severity": 2, "confidence": 0.5, "evidence_pointers": [], "reasoning": "bug",
    })
    result, warnings = run_agent(agent, {}, None, baselines)
    assert result["verdict"] == "no"
    assert warnings


def test_fires_with_real_evidence_is_not_downgraded(baselines):
    agent = _agent(lambda e, g, b: {
        "verdict": "fires", "severity": 3, "confidence": 0.8,
        "evidence_pointers": [{"step_id": 1, "selector": "#x", "signal": "test.signal"}],
        "reasoning": "genuine finding",
    })
    result, warnings = run_agent(agent, {}, None, baselines)
    assert result["verdict"] == "fires"
    assert result["severity"] == 3
    assert warnings == []


def test_no_verdict_with_empty_evidence_is_fine_no_downgrade_needed(baselines):
    agent = _agent(lambda e, g, b: no_result("nothing found"))
    result, warnings = run_agent(agent, {}, None, baselines)
    assert result["verdict"] == "no"
    assert warnings == []


# -- hard rule: required_signals missing/null -> not_assessable, assess() never called --


def test_missing_required_signal_short_circuits_to_not_assessable(baselines):
    calls = []

    def assess(e, g, b):
        calls.append(1)
        return {"verdict": "fires", "severity": 1, "confidence": 1.0, "evidence_pointers": [{"step_id": 1, "selector": None, "signal": "x"}], "reasoning": "should never run"}

    agent = _agent(assess, required_signals=["evidence.friction_metrics.friction_ratio"])
    episode = {"evidence": {"friction_metrics": {"friction_ratio": None}}}
    result, warnings = run_agent(agent, episode, None, baselines)

    assert result["verdict"] == "not_assessable"
    assert result["confidence"] == 0.0
    assert calls == []  # assess() was never invoked


def test_present_required_signal_allows_assess_to_run(baselines):
    agent = _agent(
        lambda e, g, b: no_result("checked"),
        required_signals=["evidence.friction_metrics.friction_ratio"],
    )
    episode = {"evidence": {"friction_metrics": {"friction_ratio": 1.2}}}
    result, warnings = run_agent(agent, episode, None, baselines)
    assert result["verdict"] == "no"


def test_empty_list_signal_counts_as_missing(baselines):
    agent = _agent(lambda e, g, b: no_result("x"), required_signals=["evidence.visual_asymmetry"])
    episode = {"evidence": {"visual_asymmetry": []}}
    result, warnings = run_agent(agent, episode, None, baselines)
    assert result["verdict"] == "not_assessable"


def test_group_evidence_prefixed_path_resolves_against_group_evidence_root(baselines):
    agent = _agent(lambda e, g, b: no_result("x"), required_signals=["group_evidence.paired_flow_comparison"])
    result, warnings = run_agent(agent, {}, None, baselines)
    assert result["verdict"] == "not_assessable"

    result2, _ = run_agent(agent, {}, {"paired_flow_comparison": [{"a": 1}]}, baselines)
    assert result2["verdict"] == "no"


# -- contract validation: malformed agent output raises, doesn't get silently accepted --


def test_invalid_verdict_raises_contract_violation(baselines):
    agent = _agent(lambda e, g, b: {"verdict": "definitely", "severity": None, "confidence": 0.5, "evidence_pointers": [], "reasoning": "x"})
    with pytest.raises(ContractViolation):
        run_agent(agent, {}, None, baselines)


def test_severity_out_of_range_raises(baselines):
    agent = _agent(lambda e, g, b: {"verdict": "fires", "severity": 9, "confidence": 0.5, "evidence_pointers": [{"step_id": 1, "selector": None, "signal": "x"}], "reasoning": "x"})
    with pytest.raises(ContractViolation):
        run_agent(agent, {}, None, baselines)


def test_confidence_out_of_range_raises(baselines):
    agent = _agent(lambda e, g, b: {"verdict": "no", "severity": None, "confidence": 1.5, "evidence_pointers": [], "reasoning": "x"})
    with pytest.raises(ContractViolation):
        run_agent(agent, {}, None, baselines)


def test_missing_contract_key_raises(baselines):
    agent = _agent(lambda e, g, b: {"verdict": "no", "confidence": 0.5, "evidence_pointers": [], "reasoning": "x"})
    with pytest.raises(ContractViolation):
        run_agent(agent, {}, None, baselines)


def test_evidence_pointer_missing_signal_key_raises(baselines):
    agent = _agent(lambda e, g, b: {
        "verdict": "fires", "severity": 1, "confidence": 0.5,
        "evidence_pointers": [{"step_id": 1, "selector": "#x"}], "reasoning": "x",
    })
    with pytest.raises(ContractViolation):
        run_agent(agent, {}, None, baselines)


def test_evidence_pointer_present_but_empty_signal_string_raises(baselines):
    # The key exists (so this is distinct from the missing-key case above)
    # but an empty string is just as useless for tracing a finding back
    # to what produced it -- must be rejected the same way.
    agent = _agent(lambda e, g, b: {
        "verdict": "fires", "severity": 1, "confidence": 0.5,
        "evidence_pointers": [{"step_id": 1, "selector": "#x", "signal": ""}], "reasoning": "x",
    })
    with pytest.raises(ContractViolation):
        run_agent(agent, {}, None, baselines)


def test_evidence_pointer_non_dict_entry_raises(baselines):
    agent = _agent(lambda e, g, b: {
        "verdict": "fires", "severity": 1, "confidence": 0.5,
        "evidence_pointers": ["not a dict"], "reasoning": "x",
    })
    with pytest.raises(ContractViolation):
        run_agent(agent, {}, None, baselines)


def test_empty_reasoning_raises(baselines):
    agent = _agent(lambda e, g, b: {"verdict": "no", "severity": None, "confidence": 0.5, "evidence_pointers": [], "reasoning": ""})
    with pytest.raises(ContractViolation):
        run_agent(agent, {}, None, baselines)


# -- result shape: the 8-key contract is always produced ---------------


def test_result_has_full_8_key_contract(baselines):
    agent = _agent(lambda e, g, b: no_result("x"))
    result, _ = run_agent(agent, {}, None, baselines)
    assert set(result.keys()) == {
        "attribute", "verdict", "severity", "confidence", "evidence_pointers", "reasoning", "agent_version", "agent_type",
    }
    assert result["attribute"] == "asymmetry"
    assert result["agent_version"] == "test/1.0.0"
    assert result["agent_type"] == "code"


# -- scale_severity ------------------------------------------------------


def test_scale_severity_is_1_at_threshold():
    assert scale_severity(10.0, threshold_median=10.0) == 1


def test_scale_severity_is_5_at_cap():
    assert scale_severity(30.0, threshold_median=10.0, cap_multiple=3.0) == 5


def test_scale_severity_beyond_cap_still_clamps_to_5():
    assert scale_severity(1000.0, threshold_median=10.0, cap_multiple=3.0) == 5


def test_scale_severity_is_monotonic():
    values = [scale_severity(v, threshold_median=10.0) for v in (10, 15, 20, 25, 30)]
    assert values == sorted(values)


def test_not_assessable_result_shape():
    result = not_assessable_result("no data")
    assert result["verdict"] == "not_assessable"
    assert result["confidence"] == 0.0
    assert result["evidence_pointers"] == []


# -- ui_region enrichment (Issue 2): agents never classify, the framework does --


def test_evidence_pointer_is_stamped_with_the_region_the_extractor_assigned(baselines):
    agent = _agent(lambda e, g, b: {
        "verdict": "fires", "severity": 3, "confidence": 0.8,
        "evidence_pointers": [{"step_id": 4, "selector": "#cancel-link", "signal": "test.signal"}],
        "reasoning": "measured finding",
    })
    episode = {"evidence": {"ui_regions": [{"step_id": 4, "selector": "#cancel-link", "region": "cancellation_flow"}]}}
    result, _ = run_agent(agent, episode, None, baselines)
    assert result["evidence_pointers"][0]["ui_region"] == "cancellation_flow"


def test_evidence_pointer_with_no_matching_tag_defaults_to_unclassified(baselines):
    agent = _agent(lambda e, g, b: {
        "verdict": "fires", "severity": 3, "confidence": 0.8,
        "evidence_pointers": [{"step_id": 1, "selector": "#unknown", "signal": "test.signal"}],
        "reasoning": "measured finding",
    })
    result, _ = run_agent(agent, {}, None, baselines)
    assert result["evidence_pointers"][0]["ui_region"] == "unclassified"


def test_evidence_pointer_with_null_selector_defaults_to_unclassified(baselines):
    agent = _agent(lambda e, g, b: {
        "verdict": "fires", "severity": 3, "confidence": 0.8,
        "evidence_pointers": [{"step_id": None, "selector": None, "signal": "group.signal"}],
        "reasoning": "measured finding",
    })
    episode = {"evidence": {"ui_regions": [{"step_id": 4, "selector": "#x", "region": "cancellation_flow"}]}}
    result, _ = run_agent(agent, episode, None, baselines)
    assert result["evidence_pointers"][0]["ui_region"] == "unclassified"


def test_downgraded_no_result_has_no_pointers_to_enrich(baselines):
    agent = _agent(lambda e, g, b: {
        "verdict": "fires", "severity": 4, "confidence": 0.9, "evidence_pointers": [], "reasoning": "bug",
    })
    result, warnings = run_agent(agent, {}, None, baselines)
    assert result["verdict"] == "no"
    assert result["evidence_pointers"] == []
    assert warnings


# -- hard rule: a code agent's reasoning may never read like it inspected a screenshot (Issue 4) --


def test_code_agent_visual_language_in_reasoning_raises_contract_violation(baselines):
    agent = _agent(lambda e, g, b: {
        "verdict": "fires", "severity": 3, "confidence": 0.8,
        "evidence_pointers": [{"step_id": 1, "selector": "#x", "signal": "test.signal"}],
        "reasoning": "the screenshot shows the button is clearly legible against the background",
    })
    with pytest.raises(ContractViolation):
        run_agent(agent, {}, None, baselines)


def test_code_agent_measured_language_is_fine(baselines):
    agent = _agent(lambda e, g, b: {
        "verdict": "fires", "severity": 3, "confidence": 0.8,
        "evidence_pointers": [{"step_id": 1, "selector": "#x", "signal": "test.signal"}],
        "reasoning": "contrast_ratio=1.2 is below the required threshold of 3.0",
    })
    result, _ = run_agent(agent, {}, None, baselines)
    assert result["verdict"] == "fires"
