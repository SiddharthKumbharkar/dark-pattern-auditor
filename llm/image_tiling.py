"""Splits a tall full-page screenshot into overlapping tiles before it's
sent to GPT-4o. Unlike Claude (which accepts up to 8000px tall and only
needs budget-based downscaling -- see llm/api_client.py), GPT-4o
downscales large images aggressively enough that small text on a long
page becomes unreadable. TCS-backend-specific: Part A's capture
(recorder/screenshot.py) and the Anthropic path are both untouched by
this module.

Pure function, no I/O beyond reading the one source PNG passed in --
mirrors signals/'s "pure function, no side effects" rule even though this
lives under llm/, since this output never gets written back into the
episode record.
"""

import io
from dataclasses import dataclass
from typing import List

from PIL import Image

DEFAULT_TILE_WIDTH_PX = 1280
DEFAULT_TILE_HEIGHT_PX = 2000
DEFAULT_OVERLAP_PX = 200

# A final tile shorter than this would mostly duplicate the tile before
# it (since consecutive tiles already overlap by DEFAULT_OVERLAP_PX) --
# merged into the previous tile's range instead of emitted as a
# near-empty sliver.
MIN_FINAL_TILE_HEIGHT_PX = 400


@dataclass
class ImageTile:
    index: int  # 0-based position among this screenshot's own tiles
    total: int  # how many tiles this screenshot was split into
    png_bytes: bytes
    y_offset: int  # top edge, in pixels, of this tile within the (possibly width-downscaled) source
    height: int


def tile_screenshot(
    png_bytes: bytes,
    tile_width: int = DEFAULT_TILE_WIDTH_PX,
    tile_height: int = DEFAULT_TILE_HEIGHT_PX,
    overlap: int = DEFAULT_OVERLAP_PX,
) -> List[ImageTile]:
    """Returns tiles top-to-bottom, preserving page order. A screenshot
    that already fits within one tile_height is returned as a single
    tile (index 0 of 1), re-encoded through Pillow only if it also needed
    width downscaling -- never upscaled, and never re-encoded when
    neither resize applies would be nice, but PNG round-tripping through
    Pillow is simplest and this path is not perf-critical."""
    with Image.open(io.BytesIO(png_bytes)) as img:
        img = img.convert("RGB") if img.mode not in ("RGB", "L") else img
        width, height = img.size
        if width > tile_width:
            scale = tile_width / width
            new_size = (tile_width, max(1, round(height * scale)))
            img = img.resize(new_size, Image.LANCZOS)
            width, height = img.size

        if height <= tile_height:
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return [ImageTile(index=0, total=1, png_bytes=buf.getvalue(), y_offset=0, height=height)]

        stride = max(1, tile_height - overlap)
        offsets = list(range(0, height, stride))
        while len(offsets) > 1 and (height - offsets[-1]) < MIN_FINAL_TILE_HEIGHT_PX:
            offsets.pop()

        tiles = []
        total = len(offsets)
        for index, y in enumerate(offsets):
            # The last tile always reaches the exact image bottom -- not
            # just y + tile_height -- since pruning a too-short final
            # offset above means the previous tile now has to cover the
            # remainder on its own.
            bottom = height if index == total - 1 else min(height, y + tile_height)
            crop = img.crop((0, y, width, bottom))
            buf = io.BytesIO()
            crop.save(buf, format="PNG")
            tiles.append(
                ImageTile(index=index, total=total, png_bytes=buf.getvalue(), y_offset=y, height=bottom - y)
            )
        return tiles
