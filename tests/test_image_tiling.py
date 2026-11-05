import io

from PIL import Image

from llm.image_tiling import (
    DEFAULT_OVERLAP_PX,
    DEFAULT_TILE_HEIGHT_PX,
    DEFAULT_TILE_WIDTH_PX,
    tile_screenshot,
)


def _png_bytes(width, height):
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color="white").save(buf, format="PNG")
    return buf.getvalue()


def test_short_screenshot_is_returned_as_a_single_tile():
    png = _png_bytes(800, 600)
    tiles = tile_screenshot(png)
    assert len(tiles) == 1
    assert tiles[0].index == 0
    assert tiles[0].total == 1
    assert tiles[0].y_offset == 0
    with Image.open(io.BytesIO(tiles[0].png_bytes)) as img:
        assert img.size == (800, 600)


def test_tall_screenshot_is_split_into_multiple_overlapping_tiles():
    height = DEFAULT_TILE_HEIGHT_PX * 3
    png = _png_bytes(900, height)
    tiles = tile_screenshot(png)

    assert len(tiles) > 1
    assert all(t.total == len(tiles) for t in tiles)
    assert [t.index for t in tiles] == list(range(len(tiles)))

    # consecutive tiles overlap by DEFAULT_OVERLAP_PX
    for a, b in zip(tiles, tiles[1:]):
        assert b.y_offset == a.y_offset + (DEFAULT_TILE_HEIGHT_PX - DEFAULT_OVERLAP_PX)

    # the last tile reaches exactly the bottom of the (width-adjusted) image
    with Image.open(io.BytesIO(tiles[0].png_bytes)) as first:
        width = first.width
    assert tiles[-1].y_offset + tiles[-1].height == round(height * (width / 900))


def test_wide_screenshot_is_downscaled_to_tile_width_before_tiling():
    png = _png_bytes(2560, 500)
    tiles = tile_screenshot(png)
    assert len(tiles) == 1
    with Image.open(io.BytesIO(tiles[0].png_bytes)) as img:
        assert img.width == DEFAULT_TILE_WIDTH_PX
        assert abs(img.height - round(500 * (DEFAULT_TILE_WIDTH_PX / 2560))) <= 1


def test_narrow_screenshot_is_never_upscaled():
    png = _png_bytes(400, 300)
    tiles = tile_screenshot(png)
    with Image.open(io.BytesIO(tiles[0].png_bytes)) as img:
        assert img.width == 400


def test_a_tiny_final_sliver_is_merged_into_the_previous_tile():
    # tile_height=1000, overlap=100 -> stride=900. A height of 1000+50=1050
    # would otherwise produce a second tile only 50+100=150px tall --
    # under MIN_FINAL_TILE_HEIGHT_PX, so it must be merged away.
    png = _png_bytes(800, 1050)
    tiles = tile_screenshot(png, tile_width=800, tile_height=1000, overlap=100)
    assert len(tiles) == 1
    assert tiles[0].height == 1050


def test_custom_tile_dimensions_are_respected():
    png = _png_bytes(800, 5000)
    tiles = tile_screenshot(png, tile_width=800, tile_height=1000, overlap=0)
    assert len(tiles) == 5
    assert [t.y_offset for t in tiles] == [0, 1000, 2000, 3000, 4000]
