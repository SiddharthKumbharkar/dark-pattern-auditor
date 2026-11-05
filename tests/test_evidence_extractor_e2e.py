"""End-to-end test: record a real session (headless, real Playwright
interactions) against local fixture pages, then run the actual
evidence extractor against the stored episode -- proving the whole
capture -> mask -> persist -> extract pipeline works together, not just
each piece in isolation.
"""


import pytest

from config.settings import Config
from journey.evidence_extractor import extract_evidence
from journey.schema_migration import validate_v2
from recorder.interactive_v2 import InteractiveRecorderV2

PAGE1_HTML = """<!DOCTYPE html>
<html><body>
<h1>Auralis Pro X</h1>
<p>Only 2 left in stock! Ends in 00:05:00. 42 people are viewing this.</p>
<p>Price: Rs. 8999</p>
<button id="accept-btn" type="button"
  style="background:#000000;color:#ffffff;font-size:20px;padding:12px;">Accept all cookies</button>
<button id="reject-btn" type="button"
  style="background:#eeeeee;color:#eeeeee;font-size:8px;padding:2px;">Reject all</button>
<form>
  <input type="email" required placeholder="Email for order updates" />
</form>
<a id="checkout-link" href="checkout.html">Proceed to checkout</a>
</body></html>
"""

CHECKOUT_HTML = """<!DOCTYPE html>
<html><body>
<h1>Checkout</h1>
<p>Subtotal: Rs. 8999</p>
<p>Service fee: Rs. 149</p>
<p>Grand total: Rs. 9148</p>
<button id="unsub-btn" type="button">Unsubscribe from all marketing emails</button>
</body></html>
"""


@pytest.fixture
def site_dir(tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    (site / "page1.html").write_text(PAGE1_HTML, encoding="utf-8")
    (site / "checkout.html").write_text(CHECKOUT_HTML, encoding="utf-8")
    return site


def test_full_pipeline_record_mask_extract(tmp_path, site_dir):
    storage_dir = str(tmp_path / "storage")
    rec = InteractiveRecorderV2(
        storage_dir=storage_dir,
        episode_id="episode_evidence_e2e",
        site_url=(site_dir / "page1.html").as_uri(),
        site_domain="local-test-site",
        sector="ecommerce",
        goal_id="purchase_cheapest",
        goal_description="evidence extractor e2e test",
        operator="test-operator",
        config=Config(),
    )
    page = rec.launch(headless=True)
    try:
        rec._poll_tick()  # initial load: cookie banner, price, urgency claims

        page.click("#checkout-link")
        rec._poll_tick()  # checkout page: higher total (price drift)

        page.click("#unsub-btn")
        rec._poll_tick()  # stated-vs-actual candidate
    finally:
        rec._teardown_browser()
        rec._cleanup_raw_artifacts()

    rec.finalize()

    # -- run the actual CLI-backing function against what was just stored --
    episode = extract_evidence(rec.episode_dir)
    assert validate_v2(episode) == []

    evidence = episode["evidence"]
    assert evidence["extractor_version"]
    assert evidence["extracted_at"]

    # friction_metrics: real counts from the real recording
    friction = evidence["friction_metrics"]
    assert friction["steps"] == 3
    assert friction["clicks"] == 2
    assert friction["form_fields_required"] == 1
    assert friction["friction_ratio"] is None  # not paired

    # visual_asymmetry: the accept/reject cookie buttons should be paired
    # with a real, measurable contrast/size asymmetry
    pairs = evidence["visual_asymmetry"]
    assert len(pairs) >= 1
    accept_reject = next(p for p in pairs if p["pair_pattern"] == "accept_reject")
    assert accept_reject["area_ratio"] > 1  # accept button is visibly bigger
    assert accept_reject["contrast_ratio"] > 2  # accept is much higher contrast than the ghost reject button
    assert accept_reject["font_size_ratio"] > 1

    # claim_extraction: stock count, countdown, viewer count all present
    claim_types = {c["claim_type"] for c in evidence["claim_extraction"]}
    assert "stock_count" in claim_types
    assert "countdown_timer" in claim_types
    assert "viewer_count" in claim_types
    stock_claim = next(c for c in evidence["claim_extraction"] if c["claim_type"] == "stock_count")
    assert stock_claim["normalized_value"] == 2

    # price_drift: 8999 -> 9148, one increase of 149 (the service fee)
    drift = evidence["price_drift"]
    assert drift["first_total"] == 8999.0
    assert drift["final_total"] == 9148.0
    assert drift["drift"] == 149.0
    assert len(drift["increases"]) == 1
    assert drift["increases"][0]["delta"] == 149.0

    # stated_vs_actual: the unsubscribe click, with its own step's network
    # activity (may legitimately be empty for a static local file with no
    # backend -- what matters is the claim was recognized and reported)
    stated = evidence["stated_vs_actual"]
    assert len(stated) == 1
    assert "Unsubscribe" in stated[0]["claimed_action"]
    assert isinstance(stated[0]["network_fired"], bool)

    # complexity_metrics: total_actions_required counts the 2 real clicks
    complexity = evidence["complexity_metrics"]
    assert complexity["total_actions_required"] == 2
    assert len(complexity["time_on_step"]) == 2

    # idempotency: re-running produces the same evidence shape and values
    # (extracted_at will differ, so compare everything else)
    episode_again = extract_evidence(rec.episode_dir)
    evidence_again = dict(episode_again["evidence"])
    evidence_again.pop("extracted_at")
    evidence_first = dict(evidence)
    evidence_first.pop("extracted_at")
    assert evidence_again == evidence_first
