from journey.builder import infer_page_type


def test_url_with_slash_p_slash_is_product_page():
    assert infer_page_type("https://www.example.com/p/12345", "Some Item") == "product_page"
