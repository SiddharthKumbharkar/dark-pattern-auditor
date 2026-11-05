"""Proves pipeline.mode does not change journey JSON output.

This is the "CCPA behaviour must be byte-identical when mode is 'ccpa'"
requirement, proven two ways:

  1. Regression: rebuilding a fixed synthetic journey through today's code
     with pipeline.mode="ccpa" matches tests/fixtures/golden_journey_ccpa.json,
     which was captured by running the UNMODIFIED pre-config-system
     JourneyBuilder against this exact same input, before the config
     system, ArtifactStore episode-folder change, or privacy hook existed.
     If this test ever fails, something in the journey-building path
     changed CCPA output, which the config system must never do.

  2. Invariance: building the same journey with mode="ccpa", "mechanism",
     and "both" produces byte-identical output today, because no
     mode-conditional branch exists anywhere in journey/builder.py yet --
     mechanism-mode stages are not implemented (see the repo map in
     conversation / llm/*.py, signals/state_diff.py etc. are still empty
     stubs). This test will need a new mode-specific fixture the day a
     mechanism-mode stage actually lands; that is expected, disclosed
     divergence at that point, not a silent regression today.
"""

import json
import os
from dataclasses import replace

from config.settings import Config
from journey.builder import JourneyBuilder

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
GOLDEN_PATH = os.path.join(FIXTURES_DIR, "golden_journey_ccpa.json")

DOM_STEP_2 = """
<html><body>
<table>
<tr><td>Wireless Mouse</td><td>1</td><td>Rs. 1,299</td></tr>
</table>
<div class="countdown-timer" id="deal-timer">Ends in 02:15:00</div>
</body></html>
"""

DOM_STEP_3 = """
<html><body>
<table>
<tr><td>Wireless Mouse</td><td>1</td><td>Rs. 1,299</td></tr>
<tr><td>Extended Warranty</td><td>1</td><td>Rs. 499</td></tr>
</table>
</body></html>
"""

RAW_STEPS = [
    {
        "step_id": 1,
        "timestamp": "2026-07-22T10:00:00+00:00",
        "url": "https://shop.example.com/",
        "page_title": "Example Shop - Home",
        "user_action": {"action_type": "open_page", "target_text": None, "target_role": None, "input_value_masked": None},
        "capture_excluded": False,
        "state_capture": {"screenshot_id": "step_001.png", "dom_snapshot_id": "step_001.html", "ocr_text_id": None, "accessibility_tree_id": None},
        "visible_text_summary": ["Welcome to Example Shop", "Only 3 left in stock!", "Shop Now"],
        "extraction_confidence": {"ocr_used": False, "dom_extraction_complete": True, "low_confidence_fields": []},
        "dom_html": "<html><body>Welcome to Example Shop<br>Only 3 left in stock!<br>Shop Now</body></html>",
    },
    {
        "step_id": 2,
        "timestamp": "2026-07-22T10:01:00+00:00",
        "url": "https://shop.example.com/p/wireless-mouse",
        "page_title": "Wireless Mouse - Example Shop",
        "user_action": {"action_type": "click", "target_text": "Shop Now", "target_role": "BUTTON", "input_value_masked": None},
        "capture_excluded": False,
        "state_capture": {"screenshot_id": "step_002.png", "dom_snapshot_id": "step_002.html", "ocr_text_id": None, "accessibility_tree_id": None},
        "visible_text_summary": ["Wireless Mouse", "Rs. 1,299", "Add to Cart", "Ends in 02:15:00", "112 people bought this in the last 24 hours"],
        "extraction_confidence": {"ocr_used": False, "dom_extraction_complete": True, "low_confidence_fields": []},
        "dom_html": DOM_STEP_2,
    },
    {
        "step_id": 3,
        "timestamp": "2026-07-22T10:02:00+00:00",
        "url": "https://shop.example.com/cart",
        "page_title": "Your Cart - Example Shop",
        "user_action": {"action_type": "click", "target_text": "Add to Cart", "target_role": "BUTTON", "input_value_masked": None},
        "capture_excluded": False,
        "state_capture": {"screenshot_id": "step_003.png", "dom_snapshot_id": "step_003.html", "ocr_text_id": None, "accessibility_tree_id": None},
        "visible_text_summary": ["Wireless Mouse", "Rs. 1,299", "Extended Warranty", "Rs. 499", "Checkout"],
        "extraction_confidence": {"ocr_used": False, "dom_extraction_complete": True, "low_confidence_fields": []},
        "dom_html": DOM_STEP_3,
    },
    {
        "step_id": 4,
        "timestamp": "2026-07-22T10:03:00+00:00",
        "url": "https://shop.example.com/checkout/payment",
        "user_action": {"action_type": "click", "target_text": "Checkout", "target_role": "BUTTON", "input_value_masked": None},
        "capture_excluded": True,
        "exclusion_reason": "url_pattern_match",
    },
]


def _config_with_mode(mode: str) -> Config:
    base = Config()
    return replace(base, pipeline=replace(base.pipeline, mode=mode))


def _build_journey(config: Config) -> dict:
    builder = JourneyBuilder(
        audit_id="golden_fixture_audit",
        target_domain="shop.example.com",
        storage_dir="storage",
        website_context={
            "domain": "shop.example.com",
            "industry": "ecommerce",
            "known_flow_types": ["product_browsing", "cart", "checkout"],
        },
        config=config,
    )
    for raw_step in RAW_STEPS:
        builder.add_step(raw_step)
    return builder.build()


def test_ccpa_mode_matches_pre_config_system_golden_fixture():
    with open(GOLDEN_PATH, "r", encoding="utf-8") as f:
        golden = json.load(f)

    journey = _build_journey(_config_with_mode("ccpa"))

    assert json.dumps(journey, sort_keys=True) == json.dumps(golden, sort_keys=True)


def test_pipeline_mode_does_not_affect_journey_output():
    ccpa = json.dumps(_build_journey(_config_with_mode("ccpa")), sort_keys=True)
    mechanism = json.dumps(_build_journey(_config_with_mode("mechanism")), sort_keys=True)
    both = json.dumps(_build_journey(_config_with_mode("both")), sort_keys=True)

    assert ccpa == mechanism
    assert ccpa == both
