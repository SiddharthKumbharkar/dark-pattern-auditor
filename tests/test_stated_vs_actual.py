from signals.stated_vs_actual import find_stated_vs_actual


def _step(step_id, action_type, selector=None, network_events=None):
    return {
        "step_id": step_id,
        "action": {"type": action_type, "selector": selector},
        "network_events": network_events or [],
    }


def test_unsubscribe_click_with_network_activity():
    steps = [
        _step(1, "navigate"),
        _step(2, "click", selector="#unsub-btn", network_events=[{"request_id": "r1"}, {"request_id": "r2"}]),
    ]
    styles = {1: [{"selector": "#unsub-btn", "text": "Unsubscribe from all emails"}]}
    results = find_stated_vs_actual(steps, styles)
    assert len(results) == 1
    assert results[0]["claimed_action"] == "Unsubscribe from all emails"
    assert results[0]["network_fired"] is True
    assert set(results[0]["request_ids"]) == {"r1", "r2"}


def test_cancel_click_with_no_network_activity_flags_network_fired_false():
    steps = [_step(1, "navigate"), _step(2, "click", selector="#cancel-btn", network_events=[])]
    styles = {1: [{"selector": "#cancel-btn", "text": "Cancel my plan"}]}
    results = find_stated_vs_actual(steps, styles)
    assert results[0]["network_fired"] is False
    assert results[0]["request_ids"] == []


def test_click_on_non_state_change_label_is_ignored():
    steps = [_step(1, "navigate"), _step(2, "click", selector="#buy-btn")]
    styles = {1: [{"selector": "#buy-btn", "text": "Add to cart"}]}
    assert find_stated_vs_actual(steps, styles) == []


def test_click_with_no_matching_element_in_previous_step_is_skipped():
    steps = [_step(1, "navigate"), _step(2, "click", selector="#unknown-btn")]
    styles = {1: [{"selector": "#other-btn", "text": "Cancel"}]}
    assert find_stated_vs_actual(steps, styles) == []


def test_non_click_action_is_ignored():
    steps = [_step(1, "navigate"), _step(2, "input", selector="#field")]
    styles = {1: [{"selector": "#field", "text": "Cancel"}]}
    assert find_stated_vs_actual(steps, styles) == []


def test_first_step_is_never_matched_no_preceding_state():
    steps = [_step(1, "click", selector="#cancel-btn")]
    styles = {}
    assert find_stated_vs_actual(steps, styles) == []


def test_reject_opt_out_and_delete_are_all_recognized():
    steps = [
        _step(1, "navigate"),
        _step(2, "click", selector="#a"),
        _step(3, "click", selector="#b"),
        _step(4, "click", selector="#c"),
    ]
    styles = {
        1: [{"selector": "#a", "text": "Reject all cookies"}],
        2: [{"selector": "#b", "text": "Opt out of marketing"}],
        3: [{"selector": "#c", "text": "Delete my account"}],
    }
    results = find_stated_vs_actual(steps, styles)
    assert len(results) == 3
