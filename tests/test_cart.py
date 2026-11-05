from signals.cart import compute_cart_diff, extract_cart_items


def test_new_item_with_matching_action_is_user_selected():
    previous_items = []
    current_items = [{"name": "Wireless Mouse", "quantity": 1, "user_selected": None}]
    user_actions = [{"action_type": "click", "target_text": "Add Wireless Mouse to cart"}]

    result = compute_cart_diff(previous_items, current_items, user_actions)

    assert result == [
        {"name": "Wireless Mouse", "quantity": 1, "user_selected": True, "newly_added": True}
    ]


def test_new_item_with_no_matching_action_is_not_user_selected():
    previous_items = []
    current_items = [{"name": "Wireless Mouse", "quantity": 1, "user_selected": None}]
    user_actions = [{"action_type": "click", "target_text": "Add Keyboard to cart"}]

    result = compute_cart_diff(previous_items, current_items, user_actions)

    assert result == [
        {"name": "Wireless Mouse", "quantity": 1, "user_selected": False, "newly_added": True}
    ]


def test_no_change_between_previous_and_current_returns_current_unchanged():
    previous_items = [{"name": "Wireless Mouse", "quantity": 1, "user_selected": True}]
    current_items = [{"name": "Wireless Mouse", "quantity": 1, "user_selected": True}]
    user_actions = []

    result = compute_cart_diff(previous_items, current_items, user_actions)

    assert result == [
        {"name": "Wireless Mouse", "quantity": 1, "user_selected": True, "newly_added": False}
    ]


def test_item_present_in_both_previous_and_current_is_carried_over_as_selected():
    previous_items = [{"name": "Extended Warranty Plan (auto-added)", "quantity": 1, "user_selected": False}]
    current_items = [{"name": "Extended Warranty Plan", "quantity": 1, "user_selected": None}]
    user_actions = []

    result = compute_cart_diff(previous_items, current_items, user_actions)

    assert result == [
        {"name": "Extended Warranty Plan", "quantity": 1, "user_selected": True, "newly_added": False}
    ]


def test_new_item_with_no_matching_action_has_newly_added_true():
    previous_items = []
    current_items = [{"name": "Gift Wrap", "quantity": 1, "user_selected": None}]
    user_actions = [{"action_type": "open_page", "target_text": None}]

    result = compute_cart_diff(previous_items, current_items, user_actions)

    assert result == [
        {"name": "Gift Wrap", "quantity": 1, "user_selected": False, "newly_added": True}
    ]


_CART_TABLE_DOM = """
<table class="cart-table">
  <tr><th>Item</th><th>Qty</th><th>Price</th></tr>
  <tr><td>Wireless Mouse</td><td>1</td><td>₹599</td></tr>
  <tr><td>Subtotal</td><td></td><td>₹599</td></tr>
</table>
"""


def test_subtotal_is_not_in_extracted_cart_items():
    names = [item["name"] for item in extract_cart_items([], _CART_TABLE_DOM)]
    assert "Subtotal" not in names


def test_total_is_not_in_extracted_cart_items():
    dom = _CART_TABLE_DOM.replace("Subtotal", "Total")
    names = [item["name"] for item in extract_cart_items([], dom)]
    assert "Total" not in names
