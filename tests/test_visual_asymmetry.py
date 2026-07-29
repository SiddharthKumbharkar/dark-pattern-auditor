from signals.visual_asymmetry import compute_visual_asymmetry, find_opposing_pairs, wcag_contrast_ratio


def _button(text, x, y, w, h, color="rgb(0,0,0)", bg="rgb(255,255,255)", font=16, order=0, below_fold=False):
    return {
        "selector": f"#{text.replace(' ', '-').lower()}",
        "text": text,
        "bounding_box": {"x": x, "y": y, "width": w, "height": h},
        "color": color,
        "background_color": bg,
        "font_size_px": font,
        "dom_order": order,
        "is_below_fold": below_fold,
    }


def test_finds_accept_reject_pair():
    elements = [_button("Accept all", 100, 100, 120, 40), _button("Reject all", 100, 200, 60, 20)]
    pairs = find_opposing_pairs(elements)
    assert len(pairs) == 1
    assert pairs[0][0] == "accept_reject"


def test_finds_keep_cancel_pair():
    elements = [_button("Keep subscription", 0, 0, 100, 40), _button("Cancel", 0, 100, 100, 40)]
    pairs = find_opposing_pairs(elements)
    assert any(p[0] == "keep_cancel" for p in pairs)


def test_no_pair_when_only_one_side_present():
    elements = [_button("Accept all", 0, 0, 100, 40)]
    assert find_opposing_pairs(elements) == []


def test_pairs_with_nearest_by_distance_when_multiple_candidates():
    positive = _button("Accept", 0, 0, 100, 40)
    near_negative = _button("Reject nearby", 0, 50, 100, 40)
    far_negative = _button("Reject far", 0, 900, 100, 40)
    pairs = find_opposing_pairs([positive, far_negative, near_negative])
    assert pairs[0][2]["text"] == "Reject nearby"


def test_area_ratio_reflects_size_asymmetry():
    elements = [
        _button("Accept all", 0, 0, 200, 60),   # big
        _button("Reject all", 0, 100, 40, 15),  # tiny
    ]
    result = compute_visual_asymmetry(1, elements)
    assert len(result) == 1
    assert result[0]["area_ratio"] == (200 * 60) / (40 * 15)


def test_contrast_ratio_reflects_ghost_button_pattern():
    elements = [
        _button("Accept all", 0, 0, 100, 40, color="rgb(255,255,255)", bg="rgb(0,0,0)"),  # high contrast
        _button("Reject all", 0, 100, 100, 40, color="rgb(230,230,230)", bg="rgb(240,240,240)"),  # ghost button
    ]
    result = compute_visual_asymmetry(1, elements)[0]
    assert result["contrast_ratio"] > 5  # accept is much more visually prominent


def test_font_size_ratio():
    elements = [_button("Yes", 0, 0, 50, 20, font=24), _button("No", 0, 50, 50, 20, font=8)]
    result = compute_visual_asymmetry(1, elements)[0]
    assert result["font_size_ratio"] == 3.0


def test_vertical_position_delta_sign():
    elements = [_button("Accept all", 0, 50, 50, 20), _button("Reject all", 0, 300, 50, 20)]
    result = compute_visual_asymmetry(1, elements)[0]
    assert result["vertical_position_delta_px"] == 50 - 300


def test_below_fold_flags_pass_through():
    elements = [
        _button("Accept all", 0, 50, 50, 20, below_fold=False),
        _button("Reject all", 0, 2000, 50, 20, below_fold=True),
    ]
    result = compute_visual_asymmetry(1, elements)[0]
    assert result["positive_below_fold"] is False
    assert result["negative_below_fold"] is True


def test_step_id_and_selectors_included():
    elements = [_button("Accept all", 0, 0, 50, 20), _button("Reject all", 0, 50, 50, 20)]
    result = compute_visual_asymmetry(42, elements)[0]
    assert result["step_id"] == 42
    assert result["positive_selector"] == "#accept-all"
    assert result["negative_selector"] == "#reject-all"


def test_wcag_contrast_handles_missing_color_gracefully():
    assert wcag_contrast_ratio(None, "rgb(0,0,0)") is None
    assert wcag_contrast_ratio("not-a-color", "rgb(0,0,0)") is None
