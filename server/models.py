"""Request/response shapes for the /execute and /health endpoints -- kept
separate from app.py so the wire contract is easy to read in one place.
"""

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class UsageTokens(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0


class ExecuteResponse(BaseModel):
    ok: bool
    output_text: str = ""
    output_json: Optional[Dict[str, Any]] = None
    model: Optional[str] = None
    system_fingerprint: Optional[str] = None
    usage: UsageTokens = Field(default_factory=UsageTokens)
    latency_ms: Optional[float] = None
    request_id: Optional[str] = None
    error: Optional[str] = None
    # True when response_schema was requested but the deployment doesn't
    # support strict json_schema mode, so we fell back to json_object --
    # the caller should know output_json may be looser than requested.
    used_json_object_fallback: bool = False


class HealthResponse(BaseModel):
    ok: bool
    model: Optional[str] = None
    backend: Optional[str] = None  # "azure_openai" | "openai_compatible" | "not_configured"
    configured: bool = False
