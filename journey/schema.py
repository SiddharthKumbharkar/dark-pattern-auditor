"""Canonical journey record schema (see CLAUDE.md) as Python dataclasses."""

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class UserAction:
    action_type: str  # open_page|click|scroll|form_input
    target_text: Optional[str] = None
    target_role: Optional[str] = None
    input_value_masked: Optional[str] = None


@dataclass
class StateCapture:
    screenshot_id: str
    dom_snapshot_id: str
    ocr_text_id: Optional[str] = None
    accessibility_tree_id: Optional[str] = None


@dataclass
class ExtractionConfidence:
    ocr_used: bool = False
    dom_extraction_complete: bool = True
    low_confidence_fields: List[str] = field(default_factory=list)


@dataclass
class Price:
    label: str
    value: float
    currency: str = "INR"


@dataclass
class CartItem:
    name: str
    quantity: int
    user_selected: bool
    newly_added: bool = False


@dataclass
class Popup:
    popup_id: str
    type: str
    occurrence_count_this_journey: int = 1


@dataclass
class Form:
    fields: List[str] = field(default_factory=list)
    required: List[str] = field(default_factory=list)


@dataclass
class ExtractedSignals:
    prices: List[Price] = field(default_factory=list)
    cart_items: List[CartItem] = field(default_factory=list)
    urgency_claims: List[str] = field(default_factory=list)
    social_proof_claims: List[str] = field(default_factory=list)
    timers: List[Any] = field(default_factory=list)
    popups: List[Popup] = field(default_factory=list)
    forms: List[Form] = field(default_factory=list)


@dataclass
class UiMeasurements:
    element_id: str
    role: str
    width_px: Optional[float] = None
    height_px: Optional[float] = None
    font_size_px: Optional[float] = None
    color_contrast_ratio: Optional[float] = None
    relative_size_ratio: Optional[float] = None
    is_visually_prominent: Optional[bool] = None


@dataclass
class DisclosureContext:
    signal_type: str
    disclosed: bool
    disclosure_step_id: Optional[int] = None
    disclosure_text: Optional[str] = None
    prominence: Optional[str] = None  # prominent|buried|not_disclosed
    notes: Optional[str] = None


@dataclass
class TemporalCheck:
    claim_text: str
    first_seen_step_id: int
    first_seen_timestamp: str
    revisit_timestamp: str
    still_present: bool
    revisit_step_id: Optional[int] = None
    value_changed: Optional[bool] = None
    notes: Optional[str] = None


@dataclass
class JourneyStep:
    step_id: int
    timestamp: str
    url: str
    page_title: str
    page_type: str
    user_action: UserAction
    capture_excluded: bool
    exclusion_reason: Optional[str]
    state_capture: StateCapture
    visible_text_summary: List[str]
    extracted_signals: ExtractedSignals
    extraction_confidence: ExtractionConfidence
    ui_measurements: List[UiMeasurements] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "timestamp": self.timestamp,
            "url": self.url,
            "page_title": self.page_title,
            "page_type": self.page_type,
            "user_action": asdict(self.user_action),
            "capture_excluded": self.capture_excluded,
            "exclusion_reason": self.exclusion_reason,
            "state_capture": asdict(self.state_capture),
            "visible_text_summary": list(self.visible_text_summary),
            "extracted_signals": asdict(self.extracted_signals),
            "extraction_confidence": asdict(self.extraction_confidence),
            "ui_measurements": [asdict(m) for m in self.ui_measurements],
        }


@dataclass
class JourneyRecord:
    audit_metadata: Dict[str, Any]
    website_context: Dict[str, Any]
    journey_steps: List[JourneyStep] = field(default_factory=list)
    temporal_checks: List[TemporalCheck] = field(default_factory=list)
    disclosure_context: List[DisclosureContext] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "audit_metadata": dict(self.audit_metadata),
            "website_context": dict(self.website_context),
            "journey_steps": [step.to_dict() for step in self.journey_steps],
            "temporal_checks": [asdict(c) for c in self.temporal_checks],
            "disclosure_context": [asdict(c) for c in self.disclosure_context],
        }
