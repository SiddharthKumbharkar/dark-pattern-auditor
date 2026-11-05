from signals.price_drift import compute_price_drift


def test_no_prices_anywhere_returns_all_nulls():
    result = compute_price_drift([{"step_id": 1, "page_text": "no prices here"}])
    assert result == {"first_total": None, "final_total": None, "drift": None, "increases": []}


def test_flat_price_no_drift():
    steps = [
        {"step_id": 1, "page_text": "Total: Rs. 999"},
        {"step_id": 2, "page_text": "Total: Rs. 999"},
    ]
    result = compute_price_drift(steps)
    assert result["first_total"] == 999.0
    assert result["final_total"] == 999.0
    assert result["drift"] == 0.0
    assert result["increases"] == []


def test_price_increase_detected_with_step_and_delta():
    steps = [
        {"step_id": 1, "page_text": "Total: Rs. 999"},
        {"step_id": 2, "page_text": "Total: Rs. 999. Service fee: Rs. 149. Grand total Rs. 1148"},
    ]
    result = compute_price_drift(steps)
    assert result["first_total"] == 999.0
    assert result["final_total"] == 1148.0
    assert result["drift"] == 149.0
    assert len(result["increases"]) == 1
    assert result["increases"][0] == {"step_id": 2, "delta": 149.0, "new_total": 1148.0}


def test_multiple_increases_across_steps():
    steps = [
        {"step_id": 1, "page_text": "Rs. 500"},
        {"step_id": 2, "page_text": "Rs. 650"},
        {"step_id": 3, "page_text": "Rs. 800"},
    ]
    result = compute_price_drift(steps)
    assert len(result["increases"]) == 2
    assert result["drift"] == 300.0


def test_price_decrease_is_not_counted_as_an_increase():
    steps = [
        {"step_id": 1, "page_text": "Rs. 999"},
        {"step_id": 2, "page_text": "Rs. 799"},
    ]
    result = compute_price_drift(steps)
    assert result["increases"] == []
    assert result["drift"] == -200.0


def test_step_with_no_price_is_skipped_not_a_gap():
    steps = [
        {"step_id": 1, "page_text": "Rs. 500"},
        {"step_id": 2, "page_text": "no price on this page"},
        {"step_id": 3, "page_text": "Rs. 600"},
    ]
    result = compute_price_drift(steps)
    assert result["increases"][0]["step_id"] == 3
