from signals.price import build_price_timeline, extract_prices


def test_rupee_symbol_price_is_extracted():
    result = extract_prices(["₹2,499"])
    assert result == [{"label": "price", "value": 2499.0, "currency": "INR"}]


def test_rs_prefixed_price_is_extracted():
    result = extract_prices(["Rs. 999"])
    assert result == [{"label": "price", "value": 999.0, "currency": "INR"}]


def test_no_price_returns_empty_list():
    assert extract_prices(["No price here"]) == []


def test_timeline_tracks_price_across_three_steps():
    steps = [
        {
            "step_id": 1,
            "page_type": "product_page",
            "extracted_signals": {"prices": [{"label": "price", "value": 999.0, "currency": "INR"}]},
        },
        {
            "step_id": 2,
            "page_type": "cart_page",
            "extracted_signals": {"prices": [{"label": "price", "value": 1099.0, "currency": "INR"}]},
        },
        {
            "step_id": 3,
            "page_type": "checkout_page",
            "extracted_signals": {"prices": [{"label": "price", "value": 1199.0, "currency": "INR"}]},
        },
    ]

    timeline = build_price_timeline(steps)

    assert timeline == [
        {"step_id": 1, "page_type": "product_page", "prices": [{"label": "price", "value": 999.0, "currency": "INR"}]},
        {"step_id": 2, "page_type": "cart_page", "prices": [{"label": "price", "value": 1099.0, "currency": "INR"}]},
        {"step_id": 3, "page_type": "checkout_page", "prices": [{"label": "price", "value": 1199.0, "currency": "INR"}]},
    ]
