"""The ONLY module in server/ that talks to an LLM vendor SDK -- app.py
never imports `openai` directly, mirroring the parent repo's own
"llm/ is the only layer that calls an LLM" rule (see CLAUDE.md).

Chooses Azure OpenAI vs a generic OpenAI-compatible endpoint purely from
which env vars are set:
  - AZURE_OPENAI_ENDPOINT present  -> Azure OpenAI path (needs
    AZURE_OPENAI_API_KEY, AZURE_OPENAI_DEPLOYMENT too; AZURE_OPENAI_API_VERSION
    has a default).
  - else OPENAI_API_KEY present    -> OpenAI-compatible path (OPENAI_BASE_URL
    optional -- unset means the real api.openai.com; OPENAI_MODEL defaults
    to "gpt-4o").
  - neither set                    -> BackendNotConfiguredError.

Deliberately does NOT guess which one applies when both or neither are
set in a way that's ambiguous -- see server/.env.example and README.md.
"""

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from openai import AzureOpenAI, OpenAI

DEFAULT_AZURE_API_VERSION = "2024-10-21"
DEFAULT_OPENAI_MODEL = "gpt-4o"


class BackendNotConfiguredError(RuntimeError):
    """Neither Azure nor OpenAI-compatible env vars are set, or the ones
    that ARE set are incomplete (e.g. AZURE_OPENAI_ENDPOINT without
    AZURE_OPENAI_API_KEY). Surfaced to the caller as a 500 with this exact
    message -- never a guessed endpoint/deployment."""


def _resolve_backend_kind() -> str:
    if os.environ.get("AZURE_OPENAI_ENDPOINT"):
        return "azure_openai"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai_compatible"
    return "not_configured"


def backend_status() -> Dict[str, Any]:
    """No secrets -- used by GET /health. Reports which path is active and
    the model/deployment name it would use, nothing else."""
    kind = _resolve_backend_kind()
    if kind == "azure_openai":
        model = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    elif kind == "openai_compatible":
        model = os.environ.get("OPENAI_MODEL", DEFAULT_OPENAI_MODEL)
    else:
        model = None
    return {"backend": kind, "model": model, "configured": kind != "not_configured"}


def _build_client_and_model():
    kind = _resolve_backend_kind()
    if kind == "azure_openai":
        endpoint = os.environ["AZURE_OPENAI_ENDPOINT"]
        api_key = os.environ.get("AZURE_OPENAI_API_KEY")
        deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
        if not api_key or not deployment:
            raise BackendNotConfiguredError(
                "AZURE_OPENAI_ENDPOINT is set but AZURE_OPENAI_API_KEY and/or "
                "AZURE_OPENAI_DEPLOYMENT are missing -- see server/.env.example."
            )
        api_version = os.environ.get("AZURE_OPENAI_API_VERSION", DEFAULT_AZURE_API_VERSION)
        client = AzureOpenAI(azure_endpoint=endpoint, api_key=api_key, api_version=api_version)
        return client, deployment
    if kind == "openai_compatible":
        api_key = os.environ["OPENAI_API_KEY"]
        base_url = os.environ.get("OPENAI_BASE_URL") or None
        model = os.environ.get("OPENAI_MODEL", DEFAULT_OPENAI_MODEL)
        client = OpenAI(api_key=api_key, base_url=base_url)
        return client, model
    raise BackendNotConfiguredError(
        "Neither AZURE_OPENAI_ENDPOINT nor OPENAI_API_KEY is set -- configure one of the two "
        "env-var groups in server/.env.example before calling /execute."
    )


def _image_content_parts(images_b64: List[str], image_detail: str) -> List[Dict[str, Any]]:
    return [
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}", "detail": image_detail}}
        for b64 in images_b64
    ]


def _looks_like_unsupported_response_format(exc: Exception) -> bool:
    message = str(exc).lower()
    return "response_format" in message and (
        "not supported" in message or "unsupported" in message or "invalid" in message
    )


@dataclass
class CompletionResult:
    ok: bool
    output_text: str = ""
    output_json: Optional[Dict[str, Any]] = None
    model: Optional[str] = None
    system_fingerprint: Optional[str] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0
    request_id: Optional[str] = None
    error: Optional[str] = None
    used_json_object_fallback: bool = False


def complete(
    *,
    text: str,
    system: Optional[str],
    images_b64: List[str],
    response_schema: Optional[Dict[str, Any]],
    temperature: float,
    seed: Optional[int],
    max_tokens: Optional[int],
    image_detail: str,
) -> CompletionResult:
    """One chat-completion call. Raises BackendNotConfiguredError before any
    network call if neither env-var path is usable; everything else (a
    transport error, an unsupported response_format) comes back as
    CompletionResult(ok=False, error=...) rather than raising, so app.py's
    /execute always returns a 200 with a structured error instead of a
    bare 500 for an ordinary model-side failure."""
    client, model = _build_client_and_model()

    messages: List[Dict[str, Any]] = []
    if system:
        messages.append({"role": "system", "content": system})
    user_content: List[Dict[str, Any]] = [{"type": "text", "text": text}]
    user_content.extend(_image_content_parts(images_b64, image_detail))
    messages.append({"role": "user", "content": user_content})

    kwargs: Dict[str, Any] = {"model": model, "messages": messages, "temperature": temperature}
    if seed is not None:
        kwargs["seed"] = seed
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens

    response_format = None
    if response_schema is not None:
        response_format = {
            "type": "json_schema",
            "json_schema": {"name": "structured_response", "schema": response_schema, "strict": True},
        }
        kwargs["response_format"] = response_format

    used_fallback = False
    start = time.monotonic()
    try:
        completion = client.chat.completions.create(**kwargs)
    except Exception as exc:  # noqa: BLE001 -- relay layer: surface whatever the SDK raised
        if response_format is not None and _looks_like_unsupported_response_format(exc):
            used_fallback = True
            kwargs["response_format"] = {"type": "json_object"}
            try:
                completion = client.chat.completions.create(**kwargs)
            except Exception as exc2:  # noqa: BLE001
                return CompletionResult(
                    ok=False, error=f"{type(exc2).__name__}: {exc2}",
                    latency_ms=(time.monotonic() - start) * 1000,
                )
        else:
            return CompletionResult(
                ok=False, error=f"{type(exc).__name__}: {exc}",
                latency_ms=(time.monotonic() - start) * 1000,
            )

    latency_ms = (time.monotonic() - start) * 1000
    choice = completion.choices[0]
    output_text = choice.message.content or ""
    output_json = None
    if response_schema is not None:
        try:
            output_json = json.loads(output_text)
        except (ValueError, TypeError):
            output_json = None  # malformed JSON -- caller (TCSGPT4oBackend) owns the repair retry

    usage = getattr(completion, "usage", None)
    return CompletionResult(
        ok=True,
        output_text=output_text,
        output_json=output_json,
        model=getattr(completion, "model", model),
        system_fingerprint=getattr(completion, "system_fingerprint", None),
        prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
        completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
        latency_ms=latency_ms,
        request_id=getattr(completion, "id", None),
        used_json_object_fallback=used_fallback,
    )
