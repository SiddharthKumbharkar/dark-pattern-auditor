"""signals/ui_regions.py -- deterministic region classification (Issue 2)."""

from config.ui_regions import REGION_IDS, UNCLASSIFIED_REGION
from signals.ui_regions import classify_region, compute_ui_regions


def test_unclassified_is_a_valid_region_id():
    assert UNCLASSIFIED_REGION in REGION_IDS


def test_classify_region_matches_by_selector_keyword():
    region = classify_region("button.btn-cancel-link", "Cancel my membership", "", "")
    assert region == "cancellation_flow"


def test_classify_region_matches_the_keep_side_of_a_keep_cancel_pair():
    # The "keep subscription" button has no "cancel"-shaped text of its
    # own, but it's structurally the other half of the SAME cancellation
    # decision point as the cancel link right next to it -- without this
    # keyword, a single visual_asymmetry pair's two evidence_pointers
    # (positive: keep, negative: cancel) would split across two different
    # regions purely because only one side's selector says "cancel".
    region = classify_region("button.btn-keep-subscription.mt-8", "Keep my membership", "", "")
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
    assert "text" not in tags[0]  # interactive-element tags omit text; only disclosure tags carry it


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


# -- disclosure-element tagging (non-interactive text, opt-in) ---------------


def test_disclosure_marked_element_gets_a_real_selector_and_region():
    # recorder/evidence_probe.py's interactive-elements capture never sees
    # a plain <p> -- but a page that explicitly marks one with
    # data-disclosure must still get a real, taggable selector so an LLM
    # judge that reads the text in a screenshot has something legitimate
    # to cite (see journey/mechanism_verdict_ingest.py's grounding check).
    html = (
        '<html><body><div class="cancellation-flow-page">'
        '<p data-disclosure="cancellation-fee">Cancelling now will incur a fee.</p>'
        "</div></body></html>"
    )
    steps = [{"step_id": 6}]
    dom_htmls = [html]
    computed_styles = [[{"selector": "button.confirm-btn", "text": "Confirm cancellation", "role": ""}]]

    tags = compute_ui_regions(steps, dom_htmls, computed_styles)
    disclosure_tags = [t for t in tags if t["selector"] != "button.confirm-btn"]
    assert len(disclosure_tags) == 1
    assert disclosure_tags[0]["step_id"] == 6
    assert disclosure_tags[0]["selector"]  # a real, non-empty selector was resolved
    assert disclosure_tags[0]["region"] == "cancellation_flow"  # "Cancelling" matches the cancel keyword
    assert disclosure_tags[0]["text"] == "Cancelling now will incur a fee."


def test_disclosure_tagging_runs_even_when_computed_styles_is_missing_for_that_step():
    # Unlike the interactive-elements pass, disclosure tagging reads the
    # DOM directly -- it must not depend on the interactive-elements probe
    # having succeeded for this step.
    html = '<html><body><p data-disclosure="fee">Cancelling now will incur a fee.</p></body></html>'
    steps = [{"step_id": 1}]
    dom_htmls = [html]
    computed_styles = [None]

    tags = compute_ui_regions(steps, dom_htmls, computed_styles)
    assert len(tags) == 1
    assert tags[0]["region"] == "cancellation_flow"
    assert tags[0]["text"] == "Cancelling now will incur a fee."


def test_disclosure_tagging_finds_nothing_without_the_opt_in_marker():
    # Not "tag every <p> on the page" -- only elements the page itself
    # explicitly marked.
    html = "<html><body><p>Cancelling now will incur a fee.</p></body></html>"
    steps = [{"step_id": 1}]
    dom_htmls = [html]
    computed_styles = [None]
    assert compute_ui_regions(steps, dom_htmls, computed_styles) == []


def test_disclosure_element_already_captured_as_interactive_is_not_double_tagged():
    # If the SAME element somehow carries both a computed_styles capture
    # (interactive) and the disclosure marker, it must not produce two
    # entries for the identical (step_id, selector).
    html = '<html><body><button id="fee-btn" data-disclosure="fee">Fee info</button></body></html>'
    steps = [{"step_id": 1}]
    dom_htmls = [html]
    computed_styles = [[{"selector": "#fee-btn", "text": "Fee info", "role": ""}]]

    tags = compute_ui_regions(steps, dom_htmls, computed_styles)
    assert len(tags) == 1
