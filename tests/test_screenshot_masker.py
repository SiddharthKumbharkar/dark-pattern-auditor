"""Tests for recorder/masking/screenshot_masker.py using real, small
generated PNGs (no browser needed)."""

import os

from PIL import Image

from recorder.masking.screenshot_masker import black_box_regions


def _white_image(path, width=100, height=100):
    Image.new("RGB", (width, height), color="white").save(path)


def test_black_box_draws_over_the_given_region(tmp_path):
    src = os.path.join(str(tmp_path), "src.png")
    out = os.path.join(str(tmp_path), "out.png")
    _white_image(src)

    drawn = black_box_regions(src, out, [{"x": 10, "y": 10, "width": 20, "height": 20}])
    assert drawn == 1

    image = Image.open(out).convert("RGB")
    assert image.getpixel((15, 15)) == (0, 0, 0)  # inside the box
    assert image.getpixel((90, 90)) == (255, 255, 255)  # untouched


def test_multiple_boxes_are_all_drawn(tmp_path):
    src = os.path.join(str(tmp_path), "src.png")
    out = os.path.join(str(tmp_path), "out.png")
    _white_image(src)

    boxes = [
        {"x": 0, "y": 0, "width": 10, "height": 10},
        {"x": 50, "y": 50, "width": 10, "height": 10},
    ]
    drawn = black_box_regions(src, out, boxes)
    assert drawn == 2

    image = Image.open(out).convert("RGB")
    assert image.getpixel((5, 5)) == (0, 0, 0)
    assert image.getpixel((55, 55)) == (0, 0, 0)


def test_box_entirely_off_canvas_is_skipped_not_an_error(tmp_path):
    src = os.path.join(str(tmp_path), "src.png")
    out = os.path.join(str(tmp_path), "out.png")
    _white_image(src)

    drawn = black_box_regions(src, out, [{"x": 500, "y": 500, "width": 10, "height": 10}])
    assert drawn == 0
    image = Image.open(out).convert("RGB")
    assert image.getpixel((50, 50)) == (255, 255, 255)  # nothing touched


def test_box_partially_off_canvas_is_clipped_not_skipped(tmp_path):
    src = os.path.join(str(tmp_path), "src.png")
    out = os.path.join(str(tmp_path), "out.png")
    _white_image(src)

    drawn = black_box_regions(src, out, [{"x": 90, "y": 90, "width": 50, "height": 50}])
    assert drawn == 1
    image = Image.open(out).convert("RGB")
    assert image.getpixel((95, 95)) == (0, 0, 0)


def test_no_boxes_leaves_image_untouched(tmp_path):
    src = os.path.join(str(tmp_path), "src.png")
    out = os.path.join(str(tmp_path), "out.png")
    _white_image(src)

    drawn = black_box_regions(src, out, [])
    assert drawn == 0
    image = Image.open(out).convert("RGB")
    assert image.getpixel((50, 50)) == (255, 255, 255)


def test_viewport_offset_shifts_document_relative_boxes(tmp_path):
    src = os.path.join(str(tmp_path), "src.png")
    out = os.path.join(str(tmp_path), "out.png")
    _white_image(src)

    # A box at document-relative y=110 with a viewport scrolled 100px down
    # should land at y=10 in the (viewport-only) screenshot.
    drawn = black_box_regions(
        src, out, [{"x": 10, "y": 110, "width": 10, "height": 10}], viewport_offset={"x": 0, "y": 100}
    )
    assert drawn == 1
    image = Image.open(out).convert("RGB")
    assert image.getpixel((15, 15)) == (0, 0, 0)
