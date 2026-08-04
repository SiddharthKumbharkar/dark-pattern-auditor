"""signals/ui_regions.py -- deterministic region classification (Issue 2)."""

from config.ui_regions import REGION_IDS, UNCLASSIFIED_REGION
from signals.ui_regions import classify_region, compute_ui_regions


def test_unclassified_is_a_valid_region_id():
    assert UNCLASSIFIED_REGION in REGION_IDS


def test_classify_region_matches_by_selector_keyword():
    region = classify_region("button.btn-cancel-link", "Cancel my membership", "", "")
    assert region == "cancellation_flow"


def test_classify_region_matches_by_text_keyword():
    region = classify_region("#x", "Accept cookies", "", "")
    assert region == "cookie_consent_banner"


def test_classify_region_matches_by_ancestor_landmark_context():
    region = classify_region("#save-btn", "Save", "", "form checkout-summary order-total")
    assert region == "checkout_price_summary"


def test_classify_region_falls_back_to_unclassified_when_nothing_matches():
    region = classify_region("button.generic-btn-7", "OK", "", "")
    assert region == UNCLASSIFIED_REGION


def test_classify_region_is_deterministic():
    args = ("a.link-1", "Continue", "button", "nav main-nav")
    assert classify_region(*args) == classify_region(*args)


def test_retention_offer_checked_before_cancellation_flow():
    # A retention/win-back panel sitting inside a broader cancellation
    # flow should be tagged as the more specific retention_offer, not
    # folded into cancellation_flow -- REGION_KEYWORDS ordering encodes this.
    region = classify_region("#stay-btn", "We'd hate to see you go", "", "cancel-flow-container")
    assert region == "retention_offer"


def test_compute_ui_regions_one_entry_per_interactive_element():
    html = """<html><body><nav aria-label="account settings">
        <button class="save-btn">Save</button>
    </nav></body></html>"""
    steps = [{"step_id": 1}]
    dom_htmls = [html]
    computed_styles = [[{"selector": "nav > button.save-btn", "text": "Save", "role": ""}]]

    tags = compute_ui_regions(steps, dom_htmls, computed_styles)

    assert len(tags) == 1
    assert tags[0]["step_id"] == 1
    assert tags[0]["selector"] == "nav > button.save-btn"
    assert tags[0]["region"] == "account_settings"


def test_compute_ui_regions_skips_steps_with_no_dom_or_no_computed_styles():
    steps = [{"step_id": 1}, {"step_id": 2}]
    dom_htmls = [None, "<html></html>"]
    computed_styles = [[{"selector": "#x", "text": "", "role": ""}], None]
    assert compute_ui_regions(steps, dom_htmls, computed_styles) == []


def test_compute_ui_regions_element_with_no_selector_is_skipped():
    steps = [{"step_id": 1}]
    dom_htmls = ["<html><body><button>Go</button></body></html>"]
    computed_styles = [[{"selector": None, "text": "Go", "role": ""}]]
    assert compute_ui_regions(steps, dom_htmls, computed_styles) == []


def test_compute_ui_regions_unresolvable_selector_degrades_to_keyword_only_not_a_crash():
    steps = [{"step_id": 1}]
    dom_htmls = ["<html><body></body></html>"]  # selector below matches nothing in this DOM
    computed_styles = [[{"selector": "button.cancel-btn", "text": "Cancel", "role": ""}]]
    tags = compute_ui_regions(steps, dom_htmls, computed_styles)
    assert tags[0]["region"] == "cancellation_flow"  # keyword match on selector still works
