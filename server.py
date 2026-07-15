"""FastAPI backend exposing the auditing pipeline as an HTTP API.

Orchestrates the existing Layer 1/2 pipeline (recorder/, journey/) for a
human auditor's dashboard: each POST /audit/start spins up a BrowserRecorder
in interactive mode on its own background thread, and the dashboard polls
GET /audit/{id}/status for steps as they're captured.
"""

import json
import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from config.exclusion_rules import load_exclusion_patterns
from journey.builder import JourneyBuilder
from recorder.browser import BrowserRecorder
from recorder.dom import extract_dom, extract_visible_text
from recorder.exclusion import is_excluded
from recorder.screenshot import capture_screenshot
from signals.cart import extract_cart_items
from signals.price import extract_prices
from signals.urgency import extract_social_proof_claims, extract_timers, extract_urgency_claims

STORAGE_DIR = "storage"
SCREENSHOTS_DIR = os.path.join(STORAGE_DIR, "screenshots")
DOM_DIR = os.path.join(STORAGE_DIR, "dom")

SAME_SESSION_REMINDER_DELAY = timedelta(minutes=15)
FRESH_SESSION_REMINDER_DELAY = timedelta(hours=1)
SCREENSHOT_REQUEST_TIMEOUT_SECONDS = 10

app = FastAPI(title="Dark Pattern Auditor API")

# The dashboard is a static file (dashboard/index.html) opened directly by a
# browser — typically via file://, which sends Origin: null — so it can never
# share an origin with this API. This is a localhost-only single-user dev
# tool (server binds to 127.0.0.1), so a wildcard is a reasonable tradeoff:
# there's no per-user session/auth data at stake, only local recorder state.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class AuditStartRequest(BaseModel):
    domain: str
    industry: str
    url: str


class TemporalCheckAcknowledgeRequest(BaseModel):
    check_id: str
    result: str  # persisted|changed|not_found
    notes: str = ""


@dataclass
class ScreenshotRequest:
    """Hand-off object for cross-thread manual screenshot capture.

    Playwright's sync API may only be driven from the thread that created
    it, so the FastAPI request thread cannot call recorder.page directly.
    It hands this object to the recording thread (via
    AuditSession.pending_screenshot_request) and blocks on `ready`; the
    recording thread's on_idle hook services it and sets the result.
    """

    ready: threading.Event = field(default_factory=threading.Event)
    result: dict = field(default_factory=dict)


@dataclass
class AuditSession:
    audit_id: str
    domain: str
    industry: str
    status: str  # recording|stopped|complete
    started_at: str
    output_file: str
    browser_recorder: Optional[BrowserRecorder] = None
    thread: Optional[threading.Thread] = None
    steps: List[dict] = field(default_factory=list)
    pending_temporal_checks: List[dict] = field(default_factory=list)
    acknowledged_temporal_checks: List[dict] = field(default_factory=list)
    pending_screenshot_request: Optional[ScreenshotRequest] = None
    lock: threading.Lock = field(default_factory=threading.Lock)


audits: Dict[str, AuditSession] = {}
audits_lock = threading.Lock()


def _get_session(audit_id: str) -> AuditSession:
    with audits_lock:
        session = audits.get(audit_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Unknown audit_id: {audit_id}")
    return session


def _new_audit_id() -> str:
    return f"audit_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')}Z"


def _load_dom_html(step: dict) -> str:
    dom_snapshot_id = (step.get("state_capture") or {}).get("dom_snapshot_id")
    if not dom_snapshot_id:
        return ""
    dom_path = os.path.join(DOM_DIR, dom_snapshot_id)
    try:
        with open(dom_path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def _check_for_temporal_claims(session: AuditSession, step: dict) -> None:
    """Queue a reminder for any urgency claim or timer a step surfaces.

    Raw steps from BrowserRecorder carry empty extracted_signals (signal
    extraction is Layer 2/3's job), so claims/timers are recomputed here
    from the step's own visible text and DOM rather than trusted from the
    step dict.
    """
    if step.get("capture_excluded"):
        return

    visible_text = step.get("visible_text_summary") or []
    dom_html = _load_dom_html(step)

    claims = list(extract_urgency_claims(visible_text))
    for timer in extract_timers(dom_html):
        label = timer.get("label") if isinstance(timer, dict) else str(timer)
        claims.append(label or "countdown timer")

    if not claims:
        return

    detected_at = datetime.now(timezone.utc)
    with session.lock:
        for claim in claims:
            session.pending_temporal_checks.append(
                {
                    "check_id": str(uuid.uuid4()),
                    "audit_id": session.audit_id,
                    "step_id": step["step_id"],
                    "url": step["url"],
                    "claim": claim,
                    "detected_at": detected_at.isoformat(),
                    "remind_same_session_at": (detected_at + SAME_SESSION_REMINDER_DELAY).isoformat(),
                    "remind_fresh_session_at": (detected_at + FRESH_SESSION_REMINDER_DELAY).isoformat(),
                    "status": "pending",
                }
            )


def _build_manual_screenshot_step(session: AuditSession, recorder: BrowserRecorder) -> dict:
    step_id = recorder.next_step_id()
    timestamp = datetime.now(timezone.utc).isoformat()
    url = recorder.page.url

    user_action = {
        "action_type": "manual_screenshot",
        "target_text": None,
        "target_role": None,
        "input_value_masked": None,
    }

    excluded, _matched_pattern = is_excluded(url, recorder.exclusion_patterns)
    if excluded:
        return {
            "step_id": step_id,
            "timestamp": timestamp,
            "url": url,
            "user_action": user_action,
            "capture_excluded": True,
            "exclusion_reason": "url_pattern_match",
            "state_capture": None,
            "screenshot_id": None,
        }

    timestamp_tag = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    screenshot_id = f"{session.audit_id}_manual_{timestamp_tag}.png"
    screenshot_path = os.path.join(SCREENSHOTS_DIR, screenshot_id)
    capture_screenshot(recorder.page, screenshot_path)

    visible_text = extract_visible_text(recorder.page)
    dom_html = extract_dom(recorder.page)

    step = {
        "step_id": step_id,
        "timestamp": timestamp,
        "url": url,
        "page_title": recorder.page.title(),
        "page_type": None,
        "user_action": user_action,
        "capture_excluded": False,
        "exclusion_reason": None,
        "state_capture": {
            "screenshot_id": screenshot_id,
            "dom_snapshot_id": None,
            "ocr_text_id": None,
            "accessibility_tree_id": None,
        },
        "visible_text_summary": visible_text,
        "extracted_signals": {
            "prices": extract_prices(visible_text),
            "cart_items": extract_cart_items(visible_text, dom_html),
            "urgency_claims": extract_urgency_claims(visible_text),
            "social_proof_claims": extract_social_proof_claims(visible_text),
            "timers": extract_timers(dom_html),
            "popups": [],
            "forms": [],
        },
        "extraction_confidence": {
            "ocr_used": False,
            "dom_extraction_complete": True,
            "low_confidence_fields": [],
        },
        "screenshot_id": screenshot_id,
    }
    return step


def _service_screenshot_request(session: AuditSession) -> None:
    """Runs on the recording thread via on_idle — the only thread allowed
    to touch this session's Playwright page."""
    with session.lock:
        req = session.pending_screenshot_request
        session.pending_screenshot_request = None
    if req is None:
        return

    recorder = session.browser_recorder
    try:
        step = _build_manual_screenshot_step(session, recorder)
    except Exception as exc:
        req.result = {"error": str(exc)}
        req.ready.set()
        return

    with session.lock:
        session.steps.append(step)
    if not step.get("capture_excluded"):
        _check_for_temporal_claims(session, step)

    req.result = {"screenshot_id": step.get("screenshot_id"), "step_id": step["step_id"]}
    req.ready.set()


def _record_audit(session: AuditSession, url: str) -> None:
    recorder = session.browser_recorder

    def on_step(step: dict) -> None:
        with session.lock:
            session.steps.append(step)
        _check_for_temporal_claims(session, step)

    def on_idle() -> None:
        _service_screenshot_request(session)

    try:
        recorder.start_interactive(start_url=url, on_step=on_step, on_idle=on_idle)
    except Exception as exc:
        print(f"[audit {session.audit_id}] recording thread stopped unexpectedly: {exc}")
        with session.lock:
            if session.status == "recording":
                session.status = "stopped"


@app.post("/audit/start")
def start_audit(req: AuditStartRequest):
    audit_id = _new_audit_id()
    output_file = f"output_{audit_id}.json"

    recorder = BrowserRecorder(storage_dir=STORAGE_DIR, exclusion_patterns=load_exclusion_patterns())
    session = AuditSession(
        audit_id=audit_id,
        domain=req.domain,
        industry=req.industry,
        status="recording",
        started_at=datetime.now(timezone.utc).isoformat(),
        output_file=output_file,
        browser_recorder=recorder,
    )
    with audits_lock:
        audits[audit_id] = session

    thread = threading.Thread(target=_record_audit, args=(session, req.url), daemon=True)
    session.thread = thread
    thread.start()

    return {"audit_id": audit_id, "status": "recording"}


@app.post("/audit/{audit_id}/stop")
def stop_audit(audit_id: str):
    session = _get_session(audit_id)
    if session.status != "recording":
        raise HTTPException(status_code=400, detail=f"Audit {audit_id} is not recording (status={session.status})")

    recorder = session.browser_recorder
    if recorder is not None:
        recorder._running = False
    if session.thread is not None:
        session.thread.join(timeout=5)

    with session.lock:
        steps_snapshot = list(session.steps)
        acknowledged_snapshot = list(session.acknowledged_temporal_checks)
        session.status = "complete"

    builder = JourneyBuilder(
        audit_id=session.audit_id,
        target_domain=session.domain,
        storage_dir=STORAGE_DIR,
        website_context={"domain": session.domain, "industry": session.industry},
    )
    for step in steps_snapshot:
        builder.add_step(step)
    journey = builder.build()

    value_changed_by_result = {"persisted": False, "changed": True, "not_found": None}
    journey["temporal_checks"] = [
        {
            "claim_text": check["claim"],
            "first_seen_step_id": check["step_id"],
            "first_seen_timestamp": check["detected_at"],
            "revisit_timestamp": check.get("acknowledged_at", ""),
            "still_present": check["result"] != "not_found",
            "revisit_step_id": None,
            "value_changed": value_changed_by_result.get(check["result"]),
            "notes": check.get("notes") or None,
        }
        for check in acknowledged_snapshot
    ]

    with open(session.output_file, "w", encoding="utf-8") as f:
        json.dump(journey, f, indent=2)

    return {
        "audit_id": session.audit_id,
        "status": "complete",
        "output_file": session.output_file,
        "step_count": len(steps_snapshot),
    }


@app.post("/audit/{audit_id}/screenshot")
def take_screenshot(audit_id: str):
    session = _get_session(audit_id)
    if session.status != "recording":
        raise HTTPException(status_code=400, detail=f"Audit {audit_id} is not recording (status={session.status})")

    req = ScreenshotRequest()
    with session.lock:
        session.pending_screenshot_request = req

    if not req.ready.wait(timeout=SCREENSHOT_REQUEST_TIMEOUT_SECONDS):
        raise HTTPException(status_code=504, detail="Timed out waiting for screenshot capture")

    if "error" in req.result:
        raise HTTPException(status_code=500, detail=req.result["error"])

    return req.result


@app.get("/audit/{audit_id}/status")
def get_audit_status(audit_id: str):
    session = _get_session(audit_id)
    with session.lock:
        steps = list(session.steps)
        pending_temporal_checks = list(session.pending_temporal_checks)

    return {
        "audit_id": session.audit_id,
        "domain": session.domain,
        "status": session.status,
        "step_count": len(steps),
        "steps": steps,
        "pending_temporal_checks": pending_temporal_checks,
        "started_at": session.started_at,
    }


@app.get("/audit/{audit_id}/journey")
def get_journey(audit_id: str):
    """Returns the fully-built journey record (classified page_type,
    computed extracted_signals) for the Export tab.

    Once /stop has run, the authoritative copy is the file it wrote to
    disk. Before that, this builds a side-effect-free preview from the
    steps captured so far, using the same JourneyBuilder pass /stop uses,
    without touching session state or the filesystem.
    """
    session = _get_session(audit_id)

    if session.status == "complete" and os.path.isfile(session.output_file):
        with open(session.output_file, "r", encoding="utf-8") as f:
            return json.load(f)

    with session.lock:
        steps_snapshot = list(session.steps)

    builder = JourneyBuilder(
        audit_id=session.audit_id,
        target_domain=session.domain,
        storage_dir=STORAGE_DIR,
        website_context={"domain": session.domain, "industry": session.industry},
    )
    for step in steps_snapshot:
        builder.add_step(step)
    return builder.build()


@app.get("/audit/list")
def list_audits():
    with audits_lock:
        sessions = list(audits.values())

    result = []
    for session in sessions:
        with session.lock:
            step_count = len(session.steps)
        result.append(
            {
                "audit_id": session.audit_id,
                "domain": session.domain,
                "status": session.status,
                "step_count": step_count,
                "started_at": session.started_at,
            }
        )
    return result


@app.get("/audit/{audit_id}/screenshot/{screenshot_id}")
def get_screenshot(audit_id: str, screenshot_id: str):
    _get_session(audit_id)

    # os.path.basename strips any path segments so a crafted screenshot_id
    # (e.g. "../../etc/passwd") can't escape SCREENSHOTS_DIR.
    safe_name = os.path.basename(screenshot_id)
    path = os.path.join(SCREENSHOTS_DIR, safe_name)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"Screenshot not found: {screenshot_id}")

    return FileResponse(path, media_type="image/png")


@app.post("/audit/{audit_id}/temporal_check/acknowledge")
def acknowledge_temporal_check(audit_id: str, req: TemporalCheckAcknowledgeRequest):
    session = _get_session(audit_id)

    with session.lock:
        check = next((c for c in session.pending_temporal_checks if c["check_id"] == req.check_id), None)
        if check is None:
            raise HTTPException(status_code=404, detail=f"Unknown check_id: {req.check_id}")

        check["status"] = "acknowledged"
        check["result"] = req.result
        check["notes"] = req.notes
        check["acknowledged_at"] = datetime.now(timezone.utc).isoformat()

        session.acknowledged_temporal_checks.append(dict(check))
        session.pending_temporal_checks = [
            c for c in session.pending_temporal_checks if c["check_id"] != req.check_id
        ]

    return {"check_id": req.check_id, "status": "acknowledged"}


@app.get("/reminders")
def get_reminders():
    now = datetime.now(timezone.utc)

    with audits_lock:
        sessions = list(audits.values())

    due = []
    for session in sessions:
        with session.lock:
            checks = list(session.pending_temporal_checks)
        for check in checks:
            if check["status"] != "pending":
                continue

            fresh_due_at = datetime.fromisoformat(check["remind_fresh_session_at"])
            same_due_at = datetime.fromisoformat(check["remind_same_session_at"])

            if now >= fresh_due_at:
                reminder_type, due_at = "fresh_session", check["remind_fresh_session_at"]
            elif now >= same_due_at:
                reminder_type, due_at = "same_session", check["remind_same_session_at"]
            else:
                continue

            due.append(
                {
                    "check_id": check["check_id"],
                    "audit_id": session.audit_id,
                    "domain": session.domain,
                    "claim": check["claim"],
                    "url": check["url"],
                    "reminder_type": reminder_type,
                    "due_at": due_at,
                }
            )

    return due


if __name__ == "__main__":
    os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
    uvicorn.run(app, host="127.0.0.1", port=8000)
