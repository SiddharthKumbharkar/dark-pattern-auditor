"""Tests for signals/dom_text.py -- the shared per-element text/structure
extraction multiple evidence signals (claims, price_drift, complexity,
path_deviation, friction) build on.
"""

from signals.dom_text import (
    extract_text_candidates,
    full_text,
    has_interstitial,
    has_no_interactive_elements,
    has_retention_offer,
    required_field_count,
)


# -- extract_text_candidates -----------------------------------------------


def test_extract_text_candidates_returns_own_text_with_a_selector():
    html = '<div id="promo">Only 2 left in stock</div>'
    candidates = extract_text_candidates(html)
    assert len(candidates) == 1
    assert candidates[0]["text"] == "Only 2 left in stock"
    assert candidates[0]["selector"] == "#promo"


def test_extract_text_candidates_skips_script_and_style_content():
    html = "<html><head><style>.x{color:red}</style></head><body><script>var x=1;</script><p>Real text</p></body></html>"
    candidates = extract_text_candidates(html)
    texts = [c["text"] for c in candidates]
    assert "Real text" in texts
    assert not any("color:red" in t or "var x" in t for t in texts)


def test_extract_text_candidates_skips_whitespace_only_nodes():
    html = "<div>   \n  </div><p>Actual content</p>"
    candidates = extract_text_candidates(html)
    assert [c["text"] for c in candidates] == ["Actual content"]


def test_extract_text_candidates_does_not_concatenate_descendant_text():
    # Each text node's OWN text only -- not a merged parent+child blob.
    html = "<div>Parent text<span>Child text</span></div>"
    candidates = extract_text_candidates(html)
    texts = sorted(c["text"] for c in candidates)
    assert texts == ["Child text", "Parent text"]


def test_extract_text_candidates_selector_uses_id_when_present():
    html = '<div><p id="unique">Hello</p></div>'
    candidates = extract_text_candidates(html)
    assert candidates[0]["selector"] == "#unique"


def test_extract_text_candidates_selector_disambiguates_siblings_by_nth_of_type():
    html = "<div><p>First</p><p>Second</p></div>"
    candidates = extract_text_candidates(html)
    selectors = {c["text"]: c["selector"] for c in candidates}
    assert selectors["First"] != selectors["Second"]


def test_extract_text_candidates_empty_html_returns_empty_list():
    assert extract_text_candidates("") == []
    assert extract_text_candidates(None) == []


# -- full_text ------------------------------------------------------------


def test_full_text_joins_visible_text_with_spaces():
    html = "<div><h1>Title</h1><p>Body text</p></div>"
    text = full_text(html)
    assert "Title" in text
    assert "Body text" in text


def test_full_text_empty_html_returns_empty_string():
    assert full_text("") == ""
    assert full_text(None) == ""


# -- required_field_count --------------------------------------------------


def test_required_field_count_counts_required_inputs():
    html = '<form><input required><input><select required></select><textarea required></textarea></form>'
    assert required_field_count(html) == 3


def test_required_field_count_zero_when_no_required_fields():
    html = "<form><input><input></form>"
    assert required_field_count(html) == 0


def test_required_field_count_empty_html():
    assert required_field_count("") == 0


# -- has_interstitial -------------------------------------------------------


def test_has_interstitial_detects_role_dialog():
    assert has_interstitial('<div role="dialog">Are you sure?</div>') is True


def test_has_interstitial_detects_keyword_in_class():
    assert has_interstitial('<div class="newsletter-popup">Subscribe</div>') is True
    assert has_interstitial('<div class="confirm-modal">Confirm?</div>') is True
    assert has_interstitial('<div class="overlay-backdrop"></div>') is True


def test_has_interstitial_detects_keyword_in_id():
    assert has_interstitial('<div id="cancel-confirm-dialog">Wait</div>') is True


def test_has_interstitial_false_for_ordinary_content():
    assert has_interstitial("<div class='product-card'>Item</div>") is False


def test_has_interstitial_empty_html():
    assert has_interstitial("") is False


# -- has_no_interactive_elements --------------------------------------------


def test_has_no_interactive_elements_true_for_dead_end_page():
    assert has_no_interactive_elements("<div><p>Nothing to click.</p></div>") is True


def test_has_no_interactive_elements_false_when_button_present():
    assert has_no_interactive_elements("<div><button>Continue</button></div>") is False


def test_has_no_interactive_elements_false_when_link_present():
    assert has_no_interactive_elements('<div><a href="/next">Next</a></div>') is False


def test_has_no_interactive_elements_false_when_role_button_present():
    assert has_no_interactive_elements('<div><span role="button">Go</span></div>') is False


def test_has_no_interactive_elements_empty_html_is_true():
    assert has_no_interactive_elements("") is True


# -- has_retention_offer -----------------------------------------------------


def test_has_retention_offer_detects_before_you_go():
    assert has_retention_offer("<div>Wait! Before you go, here's an offer.</div>") is True


def test_has_retention_offer_detects_percent_off():
    assert has_retention_offer("<p>Get 50% off your next order.</p>") is True


def test_has_retention_offer_detects_dont_leave_variants():
    assert has_retention_offer("<p>Don't leave just yet.</p>") is True
    assert has_retention_offer("<p>We'd hate to see you go.</p>") is True
    assert has_retention_offer("<p>Stay with us and save.</p>") is True


def test_has_retention_offer_false_for_ordinary_copy():
    assert has_retention_offer("<p>Free shipping on all orders.</p>") is False


def test_has_retention_offer_empty_html():
    assert has_retention_offer("") is False
