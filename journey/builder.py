"""Assembles captured steps into the canonical journey record (Layer 2)."""

from typing import Any, Dict, List

from journey.artifact_store import ArtifactStore
from journey.schema import (
    CartItem,
    ExtractedSignals,
    ExtractionConfidence,
    JourneyRecord,
    JourneyStep,
    Price,
    StateCapture,
    UserAction,
)
from signals.cart import compute_cart_diff, extract_cart_items
from signals.price import extract_prices
from signals.urgency import extract_social_proof_claims, extract_timers, extract_urgency_claims


def _url_path(url_lower: str) -> str:
    without_scheme = url_lower.split("://", 1)[-1]
    if "/" not in without_scheme:
        return ""
    path = without_scheme.split("/", 1)[1]
    return path.split("?", 1)[0].split("#", 1)[0]


def infer_page_type(url: str, page_title: str) -> str:
    url_lower = (url or "").lower()
    title_lower = (page_title or "").lower()

    if (
        "/p/" in url_lower
        or "/product" in url_lower
        or "/item" in url_lower
        or "/pd/" in url_lower
        or "product" in title_lower
    ):
        return "product_page"
    if "/cart" in url_lower or "/bag" in url_lower or "/basket" in url_lower or "cart" in title_lower:
        return "cart_page"
    if "/checkout" in url_lower or "/order/confirm" in url_lower or "checkout" in title_lower:
        return "checkout_page"
    if "/login" in url_lower or "/signin" in url_lower or "/signup" in url_lower or "/register" in url_lower:
        return "auth_page"
    if "/search" in url_lower or "?q=" in url_lower or "?query=" in url_lower:
        return "search_page"
    if "/category" in url_lower or "/c/" in url_lower or ("buy" in title_lower and "online" in title_lower):
        return "listing_page"
    if "/payment" in url_lower or "payment" in title_lower:
        return "payment_page"
    if "/cancel" in url_lower:
        return "cancellation_page"
    if _url_path(url_lower) in ("", "/"):
        return "homepage"
    return "unknown"


class JourneyBuilder:
    def __init__(
        self,
        audit_id: str,
        target_domain: str,
        storage_dir: str,
        website_context: Dict[str, Any],
    ):
        self.audit_id = audit_id
        self.target_domain = target_domain
        self.storage_dir = storage_dir
        self.website_context = website_context
        self.artifact_store = ArtifactStore(storage_dir)

        self.steps: List[JourneyStep] = []
        self._previous_cart_items: List[Dict[str, Any]] = []
        self._all_user_actions: List[Dict[str, Any]] = []

    def _load_dom_html(self, raw_step: Dict[str, Any]) -> str:
        if raw_step.get("dom_html"):
            return raw_step["dom_html"]

        dom_snapshot_id = (raw_step.get("state_capture") or {}).get("dom_snapshot_id")
        if not dom_snapshot_id:
            return ""

        dom_path = f"{self.artifact_store.dom_dir}/{dom_snapshot_id}"
        try:
            with open(dom_path, "r", encoding="utf-8") as f:
                return f.read()
        except OSError:
            return ""

    def add_step(self, raw_step: Dict[str, Any]) -> None:
        user_action_raw = raw_step.get("user_action") or {}
        self._all_user_actions.append(user_action_raw)

        user_action = UserAction(
            action_type=user_action_raw.get("action_type", ""),
            target_text=user_action_raw.get("target_text"),
            target_role=user_action_raw.get("target_role"),
            input_value_masked=user_action_raw.get("input_value_masked"),
        )

        if raw_step.get("capture_excluded"):
            step = JourneyStep(
                step_id=raw_step["step_id"],
                timestamp=raw_step["timestamp"],
                url=raw_step["url"],
                page_title=raw_step.get("page_title", ""),
                page_type=infer_page_type(raw_step["url"], raw_step.get("page_title", "")),
                user_action=user_action,
                capture_excluded=True,
                exclusion_reason=raw_step.get("exclusion_reason", "url_pattern_match"),
                state_capture=StateCapture(screenshot_id="", dom_snapshot_id=""),
                visible_text_summary=[],
                extracted_signals=ExtractedSignals(),
                extraction_confidence=ExtractionConfidence(),
            )
            self.steps.append(step)
            return

        visible_text = raw_step.get("visible_text_summary") or []
        dom_html = self._load_dom_html(raw_step)

        prices = extract_prices(visible_text)
        urgency_claims = extract_urgency_claims(visible_text)
        social_proof_claims = extract_social_proof_claims(visible_text)
        timers = extract_timers(dom_html)

        cart_items_raw = extract_cart_items(visible_text, dom_html)
        current_cart_items = compute_cart_diff(
            self._previous_cart_items, cart_items_raw, self._all_user_actions
        )
        self._previous_cart_items = current_cart_items

        extracted_signals = ExtractedSignals(
            prices=[Price(**p) for p in prices],
            cart_items=[CartItem(**c) for c in current_cart_items],
            urgency_claims=urgency_claims,
            social_proof_claims=social_proof_claims,
            timers=timers,
            popups=[],
            forms=[],
        )

        state_capture_raw = raw_step.get("state_capture") or {}
        extraction_confidence_raw = raw_step.get("extraction_confidence") or {}

        step = JourneyStep(
            step_id=raw_step["step_id"],
            timestamp=raw_step["timestamp"],
            url=raw_step["url"],
            page_title=raw_step.get("page_title", ""),
            page_type=infer_page_type(raw_step["url"], raw_step.get("page_title", "")),
            user_action=user_action,
            capture_excluded=False,
            exclusion_reason=None,
            state_capture=StateCapture(
                screenshot_id=state_capture_raw.get("screenshot_id", ""),
                dom_snapshot_id=state_capture_raw.get("dom_snapshot_id", ""),
                ocr_text_id=state_capture_raw.get("ocr_text_id"),
                accessibility_tree_id=state_capture_raw.get("accessibility_tree_id"),
            ),
            visible_text_summary=list(visible_text),
            extracted_signals=extracted_signals,
            extraction_confidence=ExtractionConfidence(
                ocr_used=extraction_confidence_raw.get("ocr_used", False),
                dom_extraction_complete=extraction_confidence_raw.get("dom_extraction_complete", True),
                low_confidence_fields=list(extraction_confidence_raw.get("low_confidence_fields", [])),
            ),
        )
        self.steps.append(step)

    def build(self) -> Dict[str, Any]:
        audit_metadata: Dict[str, Any] = {
            "audit_id": self.audit_id,
            "target_domain": self.target_domain,
            "audit_start_time": self.steps[0].timestamp if self.steps else None,
            "audit_end_time": self.steps[-1].timestamp if self.steps else None,
        }

        record = JourneyRecord(
            audit_metadata=audit_metadata,
            website_context=self.website_context,
            journey_steps=self.steps,
            temporal_checks=[],
            disclosure_context=[],
        )
        return record.to_dict()
