import pytest

from config.settings import Config, PrivacyConfig
from journey.builder import JourneyBuilder, infer_page_type
from journey.privacy import PrivacyValidationError


def test_url_with_slash_p_slash_is_product_page():
    assert infer_page_type("https://www.example.com/p/12345", "Some Item") == "product_page"


def _minimal_raw_step(step_id, input_value_masked=None):
    return {
        "step_id": step_id,
        "timestamp": "2026-07-22T10:00:00+00:00",
        "url": "https://example.com/",
        "page_title": "Example",
        "user_action": {
            "action_type": "open_page",
            "target_text": None,
            "target_role": None,
            "input_value_masked": input_value_masked,
        },
        "capture_excluded": False,
        "state_capture": {
            "screenshot_id": "step_001.png",
            "dom_snapshot_id": "step_001.html",
            "ocr_text_id": None,
            "accessibility_tree_id": None,
        },
        "visible_text_summary": [],
        "extraction_confidence": {"ocr_used": False, "dom_extraction_complete": True, "low_confidence_fields": []},
        "dom_html": "<html><body></body></html>",
    }


def test_journey_builder_strict_privacy_aborts_before_build(tmp_path):
    cfg = Config(privacy=PrivacyConfig(enabled=True, strict=True))
    builder = JourneyBuilder(
        audit_id="audit_privacy_test",
        target_domain="example.com",
        storage_dir=str(tmp_path),
        website_context={"domain": "example.com", "industry": "ecommerce"},
        config=cfg,
    )
    with pytest.raises(PrivacyValidationError):
        builder.add_step(_minimal_raw_step(1, input_value_masked="raw-secret-value"))
    # Nothing was appended -- build() would never see this step, so it
    # can't reach the output JSON that gets written to disk.
    assert builder.steps == []


def test_journey_builder_non_strict_privacy_collects_violations(tmp_path):
    cfg = Config(privacy=PrivacyConfig(enabled=True, strict=False))
    builder = JourneyBuilder(
        audit_id="audit_privacy_test2",
        target_domain="example.com",
        storage_dir=str(tmp_path),
        website_context={"domain": "example.com", "industry": "ecommerce"},
        config=cfg,
    )
    builder.add_step(_minimal_raw_step(1, input_value_masked="raw-secret-value"))
    assert len(builder.privacy_violations) == 1
    assert len(builder.steps) == 1
