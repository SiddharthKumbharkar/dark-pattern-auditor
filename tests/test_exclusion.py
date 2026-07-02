from recorder.exclusion import is_excluded


def test_razorpay_url_is_excluded():
    excluded, matched = is_excluded("https://example.com/api/razorpay/order")
    assert excluded is True
    assert matched == "/razorpay"


def test_payment_url_is_excluded():
    excluded, matched = is_excluded("https://example.com/payment/confirm")
    assert excluded is True
    assert matched == "/payment"


def test_normal_product_page_is_not_excluded():
    excluded, matched = is_excluded("https://example.com/product/12345")
    assert excluded is False
    assert matched == ""


def test_checkout_page_without_payment_is_not_excluded():
    excluded, matched = is_excluded("https://example.com/checkout")
    assert excluded is False
    assert matched == ""
