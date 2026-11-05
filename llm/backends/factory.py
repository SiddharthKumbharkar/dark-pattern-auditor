"""Picks which LLMBackend implementation llm/api_client.py's
call_for_judgement() dispatches to, via the LLM_BACKEND env var.
Defaults to "tcs_gpt4o" -- Anthropic is opt-in (LLM_BACKEND=anthropic),
not the fallback, now that this org runs on the TCS-hosted deployment by
default. Adding a future local-model backend (Ollama/vLLM) is one more
elif branch in get_backend(), nothing else here changes.
"""

import os
from typing import Optional

from llm.backends.anthropic_backend import AnthropicBackend
from llm.backends.base import LLMBackend
from llm.backends.tcs_gpt4o_backend import TCSGPT4oBackend

DEFAULT_BACKEND = "tcs_gpt4o"
KNOWN_BACKENDS = ("tcs_gpt4o", "anthropic")


def resolve_backend_name() -> str:
    return os.environ.get("LLM_BACKEND", DEFAULT_BACKEND)


def get_backend(name: Optional[str] = None) -> LLMBackend:
    name = name or resolve_backend_name()
    if name == "tcs_gpt4o":
        return TCSGPT4oBackend()
    if name == "anthropic":
        return AnthropicBackend()
    raise ValueError(f"Unknown LLM_BACKEND {name!r} -- must be one of {KNOWN_BACKENDS}")


def preflight_message(backend_name: Optional[str] = None) -> Optional[str]:
    """Returns a clear, actionable error message if the active backend's
    required env vars are missing, or None if it's ready to call. Used by
    auto_audit.py and record.py's --auto-audit guard so a missing
    credential fails fast -- before any browser session or evidence
    extraction -- regardless of which backend is selected."""
    name = backend_name or resolve_backend_name()
    if name == "anthropic":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return "ANTHROPIC_API_KEY is not set. Add it to .env at the project root, or export it."
        return None
    if name == "tcs_gpt4o":
        missing = [v for v in ("TCS_LLM_URL", "TCS_SESSION_COOKIE") if not os.environ.get(v)]
        if missing:
            verb = "is" if len(missing) == 1 else "are"
            return f"{' and '.join(missing)} {verb} not set. Add to .env at the project root (see .env.example)."
        return None
    return f"Unknown LLM_BACKEND {name!r} -- must be one of {KNOWN_BACKENDS}"
