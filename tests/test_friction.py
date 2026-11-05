from signals.friction import compute_friction_metrics


def _step(step_id, action_type="click"):
    return {"step_id": step_id, "action": {"type": action_type}}


def test_counts_steps_and_clicks():
    steps = [_step(1, "navigate"), _step(2, "click"), _step(3, "click"), _step(4, "input")]
    result = compute_friction_metrics(steps, [None] * 4, paired_step_count=None)
    assert result["steps"] == 4
    assert result["clicks"] == 2


def test_form_fields_required_is_max_across_steps_not_sum():
    steps = [_step(1), _step(2)]
    dom_htmls = [
        '<form><input required><input required></form>',  # 2 required
        '<form><input required></form>',  # 1 required (same form, later step)
    ]
    result = compute_friction_metrics(steps, dom_htmls, paired_step_count=None)
    assert result["form_fields_required"] == 2  # max, not 2+1=3


def test_confirmation_interstitial_detected_by_role_dialog():
    steps = [_step(1)]
    dom_htmls = ['<div role="dialog">Are you sure?</div>']
    result = compute_friction_metrics(steps, dom_htmls, paired_step_count=None)
    assert result["confirmation_interstitials"] == 1


def test_retention_offer_detected_by_phrase():
    steps = [_step(1)]
    dom_htmls = ['<div>Wait! Before you go, here is a special offer.</div>']
    result = compute_friction_metrics(steps, dom_htmls, paired_step_count=None)
    assert result["retention_offers_detected"] == 1


def test_dead_end_detected_when_no_interactive_elements():
    steps = [_step(1)]
    dom_htmls = ['<div><p>Nothing to click here.</p></div>']
    result = compute_friction_metrics(steps, dom_htmls, paired_step_count=None)
    assert result["dead_ends"] == 1


def test_page_with_button_is_not_a_dead_end():
    steps = [_step(1)]
    dom_htmls = ['<div><button>Continue</button></div>']
    result = compute_friction_metrics(steps, dom_htmls, paired_step_count=None)
    assert result["dead_ends"] == 0


def test_friction_ratio_null_when_not_paired():
    steps = [_step(1), _step(2)]
    result = compute_friction_metrics(steps, [None, None], paired_step_count=None)
    assert result["friction_ratio"] is None


def test_friction_ratio_computed_when_paired():
    steps = [_step(1), _step(2), _step(3), _step(4)]
    result = compute_friction_metrics(steps, [None] * 4, paired_step_count=2)
    assert result["friction_ratio"] == 2.0
