from signals.path_deviation import compute_path_deviation


def _step(step_id, action_type, url="https://example.com/"):
    return {"step_id": step_id, "action": {"type": action_type}, "page_url_redacted": url}


def test_new_interstitial_flagged_once():
    steps = [_step(1, "click"), _step(2, "click")]
    dom_htmls = ["<button>go</button>", '<div role="dialog">Confirm?</div>']
    events = compute_path_deviation(steps, dom_htmls)
    assert any(e["event_type"] == "forced_interstitial" and e["step_id"] == 2 for e in events)


def test_interstitial_present_on_first_step_is_still_flagged():
    steps = [_step(1, "navigate")]
    dom_htmls = ['<div role="dialog">Welcome</div>']
    events = compute_path_deviation(steps, dom_htmls)
    assert any(e["event_type"] == "forced_interstitial" for e in events)


def test_interstitial_persisting_across_steps_only_flagged_once():
    steps = [_step(1, "click"), _step(2, "click"), _step(3, "click")]
    dom_htmls = ['<div role="dialog">A</div>'] * 3
    events = compute_path_deviation(steps, dom_htmls)
    interstitial_events = [e for e in events if e["event_type"] == "forced_interstitial"]
    assert len(interstitial_events) == 1


def test_navigate_action_type_flagged_as_redirect():
    steps = [_step(1, "click"), _step(2, "navigate")]
    dom_htmls = ["<button>go</button>", "<button>go</button>"]
    events = compute_path_deviation(steps, dom_htmls)
    assert any(e["event_type"] == "redirect" and e["step_id"] == 2 for e in events)


def test_first_step_navigate_is_not_a_redirect():
    # the very first step is always a "navigate" (initial page load) --
    # not a deviation from anything.
    steps = [_step(1, "navigate")]
    dom_htmls = ["<button>go</button>"]
    events = compute_path_deviation(steps, dom_htmls)
    assert not any(e["event_type"] == "redirect" for e in events)


def test_dead_end_flagged():
    steps = [_step(1, "click")]
    dom_htmls = ["<p>no interactive elements</p>"]
    events = compute_path_deviation(steps, dom_htmls)
    assert any(e["event_type"] == "dead_end" and e["step_id"] == 1 for e in events)


def test_clean_step_produces_no_events():
    steps = [_step(1, "navigate"), _step(2, "click")]
    dom_htmls = ["<button>go</button>", "<button>next</button>"]
    events = compute_path_deviation(steps, dom_htmls)
    assert events == []
