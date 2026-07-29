"""Black-boxes regions of a screenshot (Layer 1/masking).

Pure image manipulation -- no Playwright. Boxes are document-relative
{x, y, width, height} pixel rects (see browser_probe.py), matching a
full-page screenshot's pixel space directly; for a viewport-only
screenshot, pass viewport_offset to convert them.
"""

from typing import Dict, List, Optional

from PIL import Image, ImageDraw


def black_box_regions(
    source_path: str,
    output_path: str,
    boxes: List[Dict],
    viewport_offset: Optional[Dict] = None,
) -> int:
    """Draws opaque black rectangles over `boxes` in the image at
    source_path and saves the result to output_path. Returns how many
    boxes were actually drawn (boxes fully outside the image bounds are
    skipped, not an error -- e.g. a redacted element that was off-screen
    at capture time for a viewport-only screenshot).
    """
    image = Image.open(source_path).convert("RGB")
    draw = ImageDraw.Draw(image)

    offset_x = (viewport_offset or {}).get("x", 0)
    offset_y = (viewport_offset or {}).get("y", 0)

    drawn = 0
    for box in boxes:
        x = box.get("x", 0) - offset_x
        y = box.get("y", 0) - offset_y
        width = box.get("width", 0)
        height = box.get("height", 0)
        if width <= 0 or height <= 0:
            continue

        left, top = x, y
        right, bottom = x + width, y + height
        if right <= 0 or bottom <= 0 or left >= image.width or top >= image.height:
            continue  # entirely off-canvas

        left = max(0, left)
        top = max(0, top)
        right = min(image.width, right)
        bottom = min(image.height, bottom)

        draw.rectangle([left, top, right, bottom], fill="black")
        drawn += 1

    image.save(output_path)
    return drawn
