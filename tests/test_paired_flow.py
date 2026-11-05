from signals.paired_flow import compare_paired_flows


def _friction(steps, clicks, fields, interstitials):
    return {"steps": steps, "clicks": clicks, "form_fields_required": fields, "confirmation_interstitials": interstitials, "retention_offers_detected": 0, "dead_ends": 0, "friction_ratio": None}


def test_side_by_side_counts_and_ratios():
    signup = _friction(steps=5, clicks=3, fields=2, interstitials=0)
    cancel = _friction(steps=12, clicks=8, fields=1, interstitials=3)

    result = compare_paired_flows("episode_signup", "episode_cancel", signup, cancel)

    assert result["episode_a_id"] == "episode_signup"
    assert result["episode_b_id"] == "episode_cancel"
    assert result["steps"] == {"a": 5, "b": 12}
    assert result["clicks"] == {"a": 3, "b": 8}
    assert result["fields"] == {"a": 2, "b": 1}
    assert result["interstitials"] == {"a": 0, "b": 3}
    assert result["ratios"]["steps_ratio"] == 5 / 12
    assert result["ratios"]["clicks_ratio"] == 3 / 8
    assert result["ratios"]["fields_ratio"] == 2.0
    assert result["ratios"]["interstitials_ratio"] == 0 / 3  # signup has 0 interstitials vs cancel's 3


def test_zero_denominator_ratio_is_null_not_a_crash():
    a = _friction(steps=5, clicks=0, fields=0, interstitials=0)
    b = _friction(steps=5, clicks=0, fields=0, interstitials=0)
    result = compare_paired_flows("a", "b", a, b)
    assert result["ratios"]["clicks_ratio"] is None
    assert result["ratios"]["fields_ratio"] is None
    assert result["ratios"]["interstitials_ratio"] is None
