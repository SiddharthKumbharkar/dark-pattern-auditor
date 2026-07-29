from signals.claims import extract_claims


def _candidates(*texts):
    return [{"text": t, "selector": f"#sel-{i}"} for i, t in enumerate(texts)]


def test_stock_count_extracted_and_normalized():
    claims = extract_claims(1, _candidates("Only 3 left in stock!"))
    stock = [c for c in claims if c["claim_type"] == "stock_count"]
    assert len(stock) == 1
    assert stock[0]["normalized_value"] == 3
    assert stock[0]["step_id"] == 1
    assert stock[0]["selector"] == "#sel-0"


def test_countdown_timer_hms_normalized_to_seconds():
    claims = extract_claims(1, _candidates("Ends in 02:15:30"))
    timers = [c for c in claims if c["claim_type"] == "countdown_timer"]
    assert timers[0]["normalized_value"] == 2 * 3600 + 15 * 60 + 30


def test_countdown_timer_ms_normalized_to_seconds():
    claims = extract_claims(1, _candidates("05:30 remaining"))
    timers = [c for c in claims if c["claim_type"] == "countdown_timer"]
    assert timers[0]["normalized_value"] == 5 * 60 + 30


def test_ends_in_deadline_phrase_normalized_to_seconds():
    claims = extract_claims(1, _candidates("Offer ends in 2 hours"))
    deadlines = [c for c in claims if c["claim_type"] == "deadline_phrase"]
    assert deadlines[0]["normalized_value"] == 2 * 3600


def test_viewer_count_extracted():
    claims = extract_claims(1, _candidates("42 people are viewing this"))
    viewers = [c for c in claims if c["claim_type"] == "viewer_count"]
    assert viewers[0]["normalized_value"] == 42


def test_purchase_count_extracted():
    claims = extract_claims(1, _candidates("112 people bought this today"))
    purchases = [c for c in claims if c["claim_type"] == "purchase_count"]
    assert purchases[0]["normalized_value"] == 112


def test_last_chance_has_null_normalized_value():
    claims = extract_claims(1, _candidates("Last chance!"))
    assert any(c["claim_type"] == "deadline_phrase" and c["normalized_value"] is None for c in claims)


def test_generic_urgency_phrase_falls_back_to_urgency_type():
    claims = extract_claims(1, _candidates("Hurry, act now!"))
    assert any(c["claim_type"] == "urgency_phrase" for c in claims)


def test_generic_social_proof_falls_back_to_social_proof_type():
    claims = extract_claims(1, _candidates("Best seller"))
    assert any(c["claim_type"] == "social_proof" for c in claims)


def test_ordinary_text_produces_no_claims():
    claims = extract_claims(1, _candidates("Free shipping on all orders."))
    assert claims == []


def test_duplicate_text_candidates_are_deduplicated():
    claims = extract_claims(1, _candidates("Only 3 left in stock!", "Only 3 left in stock!"))
    stock = [c for c in claims if c["claim_type"] == "stock_count"]
    assert len(stock) == 1


def test_one_text_can_produce_multiple_claim_types():
    claims = extract_claims(1, _candidates("Only 2 left! Ends in 30 minutes."))
    types = {c["claim_type"] for c in claims}
    assert "stock_count" in types
    assert "deadline_phrase" in types
