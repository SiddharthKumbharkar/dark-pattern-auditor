from signals.urgency import extract_social_proof_claims, extract_timers, extract_urgency_claims


def test_only_n_left_is_detected():
    assert extract_urgency_claims(["Only 3 left in stock!"]) == ["Only 3 left in stock!"]


def test_n_left_without_only_is_detected():
    assert extract_urgency_claims(["5 left"]) == ["5 left"]


def test_people_bought_in_last_n_days_is_detected_by_social_proof():
    text = "220 people bought this in the last 7 days"
    assert extract_social_proof_claims([text]) == [text]


def test_people_are_viewing_is_detected():
    assert extract_urgency_claims(["10 people are viewing this"]) == ["10 people are viewing this"]


def test_free_shipping_is_not_detected():
    assert extract_urgency_claims(["Free shipping on all orders"]) == []


def test_countdown_class_is_detected_by_extract_timers():
    dom_html = '<div class="countdown-timer" id="deal-timer">05:23:10</div>'
    result = extract_timers(dom_html)
    assert result == [{"element_selector": "div#deal-timer", "text_content": "05:23:10"}]
