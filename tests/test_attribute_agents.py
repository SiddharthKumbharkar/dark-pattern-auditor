"""Tests for the 7 individual attribute agents, run through run_agent()
(the framework wrapper) so the hard rules are exercised too, not just
each agent's raw assess() logic in isolation.
"""

import pytest

from attribute_agents.asymmetry import AGENT as ASYMMETRY_AGENT
from attribute_agents.base import run_agent
from attribute_agents.complexity import AGENT as COMPLEXITY_AGENT
from attribute_agents.covertness import AGENT as COVERTNESS_AGENT
from attribute_agents.deception import AGENT as DECEPTION_AGENT
from attribute_agents.disparate_treatment import AGENT as DISPARATE_TREATMENT_AGENT
from attribute_agents.information_hiding import AGENT as INFORMATION_HIDING_AGENT
from attribute_agents.restriction import AGENT as RESTRICTION_AGENT
from journey.baselines import BaselineStore


@pytest.fixture
def baselines():
    return BaselineStore()


def _pair(step_id=1, contrast=1.0, area=1.0, font=1.0, below_fold=False, pos_sel="#accept", neg_sel="#reject"):
    return {
        "step_id": step_id, "pair_pattern": "accept_reject",
        "positive_selector": pos_sel, "negative_selector": neg_sel,
        "positive_text": "Accept all", "negative_text": "Reject all",
        "area_ratio": area, "contrast_ratio": contrast, "font_size_ratio": font,
        "vertical_position_delta_px": 0, "tab_order_delta": 0,
        "positive_below_fold": False, "negative_below_fold": below_fold,
    }


# -- asymmetry -----------------------------------------------------------


def test_asymmetry_fires_on_high_contrast(baselines):
    episode = {"evidence": {"visual_asymmetry": [_pair(contrast=6.0)]}}
    result, _ = run_agent(ASYMMETRY_AGENT, episode, None, baselines)
    assert result["verdict"] == "fires"
    assert result["severity"] is not None
    assert result["evidence_pointers"]


def test_asymmetry_no_when_balanced(baselines):
    episode = {"evidence": {"visual_asymmetry": [_pair(contrast=1.1, area=1.0)]}}
    result, _ = run_agent(ASYMMETRY_AGENT, episode, None, baselines)
    assert result["verdict"] == "no"


def test_asymmetry_unsure_when_contrast_in_borderline_band(baselines):
    # asymmetry_contrast_ratio_threshold: median=3.0, p75=4.5 -- 3.5 falls
    # inside [median, p75), below the clearly-firing value used above (6.0).
    episode = {"evidence": {"visual_asymmetry": [_pair(contrast=3.5, area=1.0)]}}
    result, _ = run_agent(ASYMMETRY_AGENT, episode, None, baselines)
    assert result["verdict"] == "unsure"
    assert result["severity"] is None
    assert result["evidence_pointers"]


def test_asymmetry_not_assessable_when_no_pairs_found(baselines):
    episode = {"evidence": {"visual_asymmetry": []}}
    result, _ = run_agent(ASYMMETRY_AGENT, episode, None, baselines)
    assert result["verdict"] == "not_assessable"


# -- covertness (explicit Stage-2 stub -- never fakes a verdict) ----------


def test_covertness_stub_is_not_assessable_even_on_input_that_would_have_fired(baselines):
    # This exact shape (negative option below the fold) fired under the
    # old covertness heuristic. The stub must not resurrect that logic.
    episode = {"evidence": {"visual_asymmetry": [_pair(contrast=1.0, below_fold=True)]}}
    result, _ = run_agent(COVERTNESS_AGENT, episode, None, baselines)
    assert result["verdict"] == "not_assessable"
    assert result["reasoning"] == "requires LLM judgement — Stage 2"
    assert result["evidence_pointers"] == []
    assert result["severity"] is None


def test_covertness_stub_is_not_assessable_on_empty_input(baselines):
    episode = {"evidence": {"visual_asymmetry": []}}
    result, _ = run_agent(COVERTNESS_AGENT, episode, None, baselines)
    assert result["verdict"] == "not_assessable"
    assert result["reasoning"] == "requires LLM judgement — Stage 2"


# -- deception -------------------------------------------------------------


def test_deception_not_assessable_with_no_data_at_all(baselines):
    episode = {"evidence": {"stated_vs_actual": []}}
    result, _ = run_agent(DECEPTION_AGENT, episode, None, baselines)
    assert result["verdict"] == "not_assessable"


def test_deception_no_when_network_fired_and_no_group_issues(baselines):
    episode = {"evidence": {"stated_vs_actual": [{"claimed_action": "Cancel", "step_id": 3, "network_fired": True, "request_ids": ["r1"]}]}}
    result, _ = run_agent(DECEPTION_AGENT, episode, None, baselines)
    assert result["verdict"] == "no"


def test_deception_fires_when_claimed_action_has_no_network_activity(baselines):
    episode = {"evidence": {"stated_vs_actual": [{"claimed_action": "Unsubscribe", "step_id": 5, "network_fired": False, "request_ids": []}]}}
    result, _ = run_agent(DECEPTION_AGENT, episode, None, baselines)
    assert result["verdict"] == "fires"
    assert result["evidence_pointers"][0]["step_id"] == 5


def test_deception_fires_from_group_evidence_implausible_claim(baselines):
    episode = {"evidence": {}}
    group_evidence = {"claim_persistence": [{"claim_type": "stock_count", "selector": "#s", "verdict": "implausible"}], "timer_reset_detection": []}
    result, _ = run_agent(DECEPTION_AGENT, episode, group_evidence, baselines)
    assert result["verdict"] == "fires"


def test_deception_fires_from_timer_reset(baselines):
    episode = {"evidence": {}}
    group_evidence = {"claim_persistence": [], "timer_reset_detection": [{"selector": "#t", "reset_detected": True}]}
    result, _ = run_agent(DECEPTION_AGENT, episode, group_evidence, baselines)
    assert result["verdict"] == "fires"


def test_deception_unsure_when_only_insufficient_data(baselines):
    episode = {"evidence": {"stated_vs_actual": []}}
    group_evidence = {
        "claim_persistence": [{"claim_type": "stock_count", "selector": "#s", "verdict": "insufficient_data"}],
        "timer_reset_detection": [],
    }
    result, _ = run_agent(DECEPTION_AGENT, episode, group_evidence, baselines)
    assert result["verdict"] == "unsure"
    assert result["severity"] is None
    assert result["evidence_pointers"]


def test_deception_confirmed_finding_takes_priority_over_insufficient_data(baselines):
    episode = {"evidence": {"stated_vs_actual": [{"claimed_action": "Cancel", "step_id": 1, "network_fired": False, "request_ids": []}]}}
    group_evidence = {
        "claim_persistence": [{"claim_type": "stock_count", "selector": "#s", "verdict": "insufficient_data"}],
        "timer_reset_detection": [],
    }
    result, _ = run_agent(DECEPTION_AGENT, episode, group_evidence, baselines)
    assert result["verdict"] == "fires"


def test_deception_never_infers_from_aggressive_wording_alone(baselines):
    # An "aggressive"-sounding claim with a network request that DID fire,
    # a persistence verdict of verified_true, and no timer reset -- i.e.
    # exactly the shape of a genuine, functioning claim. Wording (however
    # dramatic) plays no role: this module never reads claim_text at all.
    episode = {"evidence": {"stated_vs_actual": [
        {"claimed_action": "ACT NOW OR LOSE YOUR ACCOUNT FOREVER!!!", "step_id": 1, "network_fired": True, "request_ids": ["r1"]}
    ]}}
    group_evidence = {
        "claim_persistence": [{"claim_type": "urgency_phrase", "selector": "#s", "verdict": "verified_true"}],
        "timer_reset_detection": [{"selector": "#t", "reset_detected": False}],
    }
    result, _ = run_agent(DECEPTION_AGENT, episode, group_evidence, baselines)
    assert result["verdict"] == "no"


# -- information_hiding (explicit Stage-2 stub -- never fakes a verdict) --


def test_information_hiding_stub_is_not_assessable_even_on_input_that_would_have_fired(baselines):
    # This exact shape (a late-revealed fee) fired under the old
    # price-drift heuristic. The stub must not resurrect that logic.
    episode = {"evidence": {"price_drift": {
        "first_total": 100.0, "final_total": 130.0, "drift": 30.0,
        "increases": [{"step_id": 4, "delta": 30.0, "new_total": 130.0}],
    }}}
    result, _ = run_agent(INFORMATION_HIDING_AGENT, episode, None, baselines)
    assert result["verdict"] == "not_assessable"
    assert result["reasoning"] == "requires LLM judgement — Stage 2"
    assert result["evidence_pointers"] == []
    assert result["severity"] is None


def test_information_hiding_stub_is_not_assessable_when_no_price_ever_shown(baselines):
    episode = {"evidence": {"price_drift": {"first_total": None, "final_total": None, "drift": None, "increases": []}}}
    result, _ = run_agent(INFORMATION_HIDING_AGENT, episode, None, baselines)
    assert result["verdict"] == "not_assessable"
    assert result["reasoning"] == "requires LLM judgement — Stage 2"


# -- restriction -------------------------------------------------------------
# baselines: restriction_friction_ratio_threshold median=1.5 p75=2.0,
# restriction_p75_factor median=1.3 (fires >= 2.0*1.3=2.6), so:
#   clean:  ratio < 1.5
#   unsure: 1.5 <= ratio < 2.6
#   fires:  ratio >= 2.6
# restriction_forced_interstitial_count_threshold median=1.0 p75=2.0
# (fires >= 2.0*1.3=2.6, i.e. count>=3).


def _restriction_episode(episode_id="e1", friction_ratio=None, forced_interstitial_count=0, dom_captured=True):
    return {
        "episode": {"episode_id": episode_id},
        "evidence": {
            "friction_metrics": {"friction_ratio": friction_ratio},
            "path_deviation": [
                {"step_id": i + 1, "event_type": "forced_interstitial", "from_url": "x", "to_url": "y"}
                for i in range(forced_interstitial_count)
            ],
        },
        # dom_snapshot_masked_path is what signals/path_deviation.py's
        # forced-interstitial count is actually derived from at
        # extract-evidence time -- omitting it (dom_captured=False) is how
        # a real episode ends up with a vacuous 0 count: no step ever had a
        # masked DOM snapshot to look at, distinct from "looked and found
        # none".
        "steps": [
            {"step_id": 1, "dom_snapshot_masked_path": "dom/step_001.html" if dom_captured else None, "capture_error": None},
        ],
    }


def _paired_flow_group_evidence(episode_id="e1", other_id="e2"):
    return {"paired_flow_comparison": [{
        "episode_a_id": episode_id, "episode_b_id": other_id,
        "steps": {"a": 1, "b": 1}, "clicks": {"a": 1, "b": 1}, "fields": {"a": 1, "b": 1}, "interstitials": {"a": 1, "b": 1},
        "ratios": {"steps_ratio": 1.0, "clicks_ratio": 1.0, "fields_ratio": 1.0, "interstitials_ratio": 1.0},
    }]}


def test_restriction_not_assessable_when_no_group_evidence_at_all(baselines):
    episode = _restriction_episode(friction_ratio=3.0)
    result, _ = run_agent(RESTRICTION_AGENT, episode, None, baselines)
    assert result["verdict"] == "not_assessable"


def test_restriction_not_assessable_when_episode_not_in_any_pair(baselines):
    episode = _restriction_episode(episode_id="e_unrelated", friction_ratio=3.0)
    group_evidence = _paired_flow_group_evidence(episode_id="e1", other_id="e2")
    result, _ = run_agent(RESTRICTION_AGENT, episode, group_evidence, baselines)
    assert result["verdict"] == "not_assessable"


def test_restriction_no_when_both_clean(baselines):
    episode = _restriction_episode(friction_ratio=1.0, forced_interstitial_count=0)
    result, _ = run_agent(RESTRICTION_AGENT, episode, _paired_flow_group_evidence(), baselines)
    assert result["verdict"] == "no"


def test_restriction_unsure_when_ratio_in_borderline_band(baselines):
    episode = _restriction_episode(friction_ratio=1.8, forced_interstitial_count=0)
    result, _ = run_agent(RESTRICTION_AGENT, episode, _paired_flow_group_evidence(), baselines)
    assert result["verdict"] == "unsure"
    assert result["severity"] is None
    assert result["evidence_pointers"]


def test_restriction_fires_when_ratio_past_p75_times_factor(baselines):
    episode = _restriction_episode(friction_ratio=3.0, forced_interstitial_count=0)
    result, _ = run_agent(RESTRICTION_AGENT, episode, _paired_flow_group_evidence(), baselines)
    assert result["verdict"] == "fires"
    assert result["severity"] is not None
    assert result["evidence_pointers"]


def test_restriction_fires_via_forced_interstitial_path_alone(baselines):
    episode = _restriction_episode(friction_ratio=1.0, forced_interstitial_count=3)
    result, _ = run_agent(RESTRICTION_AGENT, episode, _paired_flow_group_evidence(), baselines)
    assert result["verdict"] == "fires"
    assert any(p["signal"] == "path_deviation.forced_interstitial" for p in result["evidence_pointers"])


def test_restriction_not_assessable_when_neither_dimension_is_measurable(baselines):
    # friction_ratio never computed (not paired at extract-evidence time)
    # AND no step ever had a masked DOM snapshot to count interstitials
    # from -- there is genuinely nothing to assess restriction from, and
    # this must not silently read as "no".
    episode = _restriction_episode(friction_ratio=None, forced_interstitial_count=0, dom_captured=False)
    result, _ = run_agent(RESTRICTION_AGENT, episode, _paired_flow_group_evidence(), baselines)
    assert result["verdict"] == "not_assessable"


def test_restriction_no_when_ratio_clean_and_interstitial_count_not_measurable(baselines):
    # forced_interstitial_count=0 here is vacuous (dom_captured=False), so
    # it must be SKIPPED, not treated as a second "clean" data point --
    # but the ratio dimension IS genuinely measured and clean, so the
    # overall verdict is still "no", not "not_assessable".
    episode = _restriction_episode(friction_ratio=1.0, forced_interstitial_count=0, dom_captured=False)
    result, _ = run_agent(RESTRICTION_AGENT, episode, _paired_flow_group_evidence(), baselines)
    assert result["verdict"] == "no"
    assert "not available" not in result["reasoning"]
    assert "not assessable" in result["reasoning"]
    # never claim the unmeasured interstitial count was "below threshold"
    assert "0 forced interstitial" not in result["reasoning"]


def test_restriction_fires_via_ratio_even_when_interstitial_count_not_measurable(baselines):
    # A vacuous 0 forced-interstitial count must not be able to drag a
    # genuine "fires" on the ratio dimension down to "unsure" or "no" --
    # it's simply excluded from the aggregation, same as complexity.py
    # skips an unmeasurable dimension rather than faking a clean one.
    episode = _restriction_episode(friction_ratio=3.0, forced_interstitial_count=0, dom_captured=False)
    result, _ = run_agent(RESTRICTION_AGENT, episode, _paired_flow_group_evidence(), baselines)
    assert result["verdict"] == "fires"


# -- disparate_treatment (explicit Stage-2 stub -- never fakes a verdict) --


def _flow_comparison(a_id, b_id, ratios):
    return {
        "episode_a_id": a_id, "episode_b_id": b_id,
        "steps": {"a": 1, "b": 1}, "clicks": {"a": 1, "b": 1}, "fields": {"a": 1, "b": 1}, "interstitials": {"a": 1, "b": 1},
        "ratios": ratios,
    }


def test_disparate_treatment_stub_is_not_assessable_even_on_input_that_would_have_fired(baselines):
    # This exact shape (an extreme ratio deviation) fired under the old
    # ratio-deviation heuristic. The stub must not resurrect that logic.
    episode = {"episode": {"episode_id": "e1"}}
    group_evidence = {"paired_flow_comparison": [_flow_comparison("e1", "e2", {"steps_ratio": 0.2, "clicks_ratio": 1.0, "fields_ratio": 1.0, "interstitials_ratio": 1.0})]}
    result, _ = run_agent(DISPARATE_TREATMENT_AGENT, episode, group_evidence, baselines)
    assert result["verdict"] == "not_assessable"
    assert result["reasoning"] == "requires LLM judgement — Stage 2"
    assert result["evidence_pointers"] == []
    assert result["severity"] is None


def test_disparate_treatment_stub_is_not_assessable_when_no_group_evidence(baselines):
    episode = {"episode": {"episode_id": "e1"}}
    result, _ = run_agent(DISPARATE_TREATMENT_AGENT, episode, None, baselines)
    assert result["verdict"] == "not_assessable"
    assert result["reasoning"] == "requires LLM judgement — Stage 2"


# -- complexity ---------------------------------------------------------


def test_complexity_not_assessable_when_no_consent_copy_found(baselines):
    episode = {"evidence": {"complexity_metrics": {"copy_readability": []}}}
    result, _ = run_agent(COMPLEXITY_AGENT, episode, None, baselines)
    assert result["verdict"] == "not_assessable"


def test_complexity_no_when_reading_grade_low(baselines):
    episode = {"evidence": {"complexity_metrics": {"copy_readability": [{"step_id": 2, "flesch_kincaid_grade": 5.0, "negation_count": 0, "double_negative_count": 0}]}}}
    result, _ = run_agent(COMPLEXITY_AGENT, episode, None, baselines)
    assert result["verdict"] == "no"


def test_complexity_fires_when_reading_grade_high(baselines):
    episode = {"evidence": {"complexity_metrics": {"copy_readability": [{"step_id": 2, "flesch_kincaid_grade": 18.0, "negation_count": 3, "double_negative_count": 1}]}}}
    result, _ = run_agent(COMPLEXITY_AGENT, episode, None, baselines)
    assert result["verdict"] == "fires"
    assert result["evidence_pointers"][0]["step_id"] == 2


def test_complexity_unsure_when_reading_grade_in_borderline_band(baselines):
    # global reading-grade threshold: median=12.0, p75=14.0
    episode = {"evidence": {"complexity_metrics": {"copy_readability": [{"step_id": 2, "flesch_kincaid_grade": 13.0, "negation_count": 0, "double_negative_count": 0}]}}}
    result, _ = run_agent(COMPLEXITY_AGENT, episode, None, baselines)
    assert result["verdict"] == "unsure"
    assert result["severity"] is None


def test_complexity_fires_on_option_count_alone(baselines):
    # option_count threshold: median=4.0, p75=7.0 -- no consent copy at all
    episode = {"evidence": {"complexity_metrics": {"option_counts": [{"step_id": 3, "option_count": 10}]}}}
    result, _ = run_agent(COMPLEXITY_AGENT, episode, None, baselines)
    assert result["verdict"] == "fires"
    assert result["evidence_pointers"][0]["step_id"] == 3
    assert result["evidence_pointers"][0]["signal"] == "complexity_metrics.option_counts.option_count"


def test_complexity_fires_on_total_actions_alone(baselines):
    # total_actions threshold: median=6.0, p75=10.0
    episode = {"evidence": {"complexity_metrics": {"total_actions_required": 15}}}
    result, _ = run_agent(COMPLEXITY_AGENT, episode, None, baselines)
    assert result["verdict"] == "fires"
    assert result["evidence_pointers"][0]["signal"] == "complexity_metrics.total_actions_required"


def test_complexity_not_assessable_when_all_three_dimensions_are_empty(baselines):
    episode = {"evidence": {"complexity_metrics": {"option_counts": [], "copy_readability": [], "time_on_step": []}}}
    result, _ = run_agent(COMPLEXITY_AGENT, episode, None, baselines)
    assert result["verdict"] == "not_assessable"


def test_complexity_goal_scoped_threshold_changes_the_verdict(baselines):
    # Same grade=15.0: fires against the global threshold (p75=14.0) but
    # only "unsure" against cancel_subscription's own, more lenient
    # threshold (median=14.0, p75=17.0) -- proves goal-scoping is actually
    # wired into the agent, not just the baseline store.
    copy_readability = [{"step_id": 2, "flesch_kincaid_grade": 15.0, "negation_count": 0, "double_negative_count": 0}]

    global_episode = {"evidence": {"complexity_metrics": {"copy_readability": copy_readability}}}
    global_result, _ = run_agent(COMPLEXITY_AGENT, global_episode, None, baselines)
    assert global_result["verdict"] == "fires"

    scoped_episode = {
        "episode": {"goal": "cancel_subscription"},
        "evidence": {"complexity_metrics": {"copy_readability": copy_readability}},
    }
    scoped_result, _ = run_agent(COMPLEXITY_AGENT, scoped_episode, None, baselines)
    assert scoped_result["verdict"] == "unsure"


# -- every agent, every verdict path: contract shape holds --------------


@pytest.mark.parametrize("agent", [
    ASYMMETRY_AGENT, COVERTNESS_AGENT, DECEPTION_AGENT, INFORMATION_HIDING_AGENT,
    RESTRICTION_AGENT, DISPARATE_TREATMENT_AGENT, COMPLEXITY_AGENT,
])
def test_every_agent_produces_the_full_contract_on_empty_input(agent, baselines):
    result, warnings = run_agent(agent, {}, None, baselines)
    assert set(result.keys()) == {
        "attribute", "verdict", "severity", "confidence", "evidence_pointers", "reasoning", "agent_version", "agent_type",
    }
    assert result["verdict"] in ("fires", "no", "unsure", "not_assessable")
    assert result["agent_type"] == "code"
