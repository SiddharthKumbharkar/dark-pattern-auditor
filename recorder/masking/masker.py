"""Orchestrates DOM + screenshot masking for one step capture (Layer 1).

The only place recorder/interactive_v2.py calls into recorder/masking/ --
everything else in this package is used through here. Runs strictly
BETWEEN capture and persistence: nothing this module touches is written
to the episode folder by anyone upstream of it.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from bs4 import BeautifulSoup
from playwright.sync_api import Page

from recorder.masking.browser_probe import bounding_boxes_for_selectors, form_field_metadata
from recorder.masking.dom_masker import mask_dom_html
from recorder.masking.patterns import find_card_numbers, find_emails, find_phone_numbers
from recorder.masking.screenshot_masker import black_box_regions

MASKER_VERSION = "privacy_masker/1.0.0"


def residual_pii_found(masked_html: str) -> bool:
    """Self-check re-scan of ALREADY-masked HTML for anything that
    slipped through -- what strict mode (recorder/interactive_v2.py)
    relies on to decide whether to withhold an artifact / abort the
    session. Tag-stripped text-only scan; good enough for a safety net,
    not a claim of exhaustive coverage."""
    text = BeautifulSoup(masked_html or "", "html.parser").get_text(" ")
    return (
        any(True for _ in find_card_numbers(text))
        or any(True for _ in find_emails(text))
        or any(True for _ in find_phone_numbers(text))
    )


@dataclass
class StepMaskResult:
    masked_dom_html: Optional[str] = None
    dom_redaction_kinds: List[str] = field(default_factory=list)
    boxes_to_black_out: List[Dict] = field(default_factory=list)
    residual_pii_found: bool = False
    error: Optional[str] = None


def mask_dom_for_step(
    page: Page, dom_html: str, field_denylist: Optional[List[str]] = None
) -> StepMaskResult:
    try:
        fields = form_field_metadata(page)
        result = mask_dom_html(dom_html, fields, field_denylist)

        boxes = list(result.redacted_boxes)
        if result.text_redaction_selectors:
            boxes.extend(bounding_boxes_for_selectors(page, result.text_redaction_selectors))

        return StepMaskResult(
            masked_dom_html=result.masked_html,
            dom_redaction_kinds=result.redaction_kinds,
            boxes_to_black_out=boxes,
            residual_pii_found=residual_pii_found(result.masked_html),
        )
    except Exception as exc:
        return StepMaskResult(error=str(exc))


def mask_screenshot_for_step(raw_screenshot_path: str, masked_screenshot_path: str, boxes: List[Dict]) -> Optional[str]:
    """Returns an error message string on failure, None on success."""
    try:
        black_box_regions(raw_screenshot_path, masked_screenshot_path, boxes)
        return None
    except Exception as exc:
        return str(exc)
