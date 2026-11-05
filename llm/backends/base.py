"""Backend-agnostic interface every LLM transport implements -- Anthropic
Claude, TCS-hosted GPT-4o, and (per this interface's whole point) any
future local-model backend (Ollama/vLLM) without llm/api_client.py's
callers needing to change.

llm/api_client.py's call_for_judgement() remains the one place every
existing caller (auto_audit.py, tests) goes through; for anything other
than an explicitly-injected Anthropic `client=` kwarg (the existing test
seam, preserved byte-for-byte -- see that function's docstring), it
dispatches to whichever backend LLM_BACKEND selects (see factory.py) and
unwraps the LLMResult back into the plain judgement dict shape callers
already expect.
"""

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class LLMResult:
    ok: bool
    output_text: str = ""
    output_json: Optional[Dict] = None
    model: Optional[str] = None
    system_fingerprint: Optional[str] = None
    # At minimum {"prompt_tokens": int, "completion_tokens": int} -- a
    # backend may add vendor-specific extra keys (e.g. Anthropic's
    # cache_read/cache_creation token counts).
    usage: Dict = field(default_factory=dict)
    latency_ms: Optional[float] = None
    request_id: Optional[str] = None
    error: Optional[str] = None


class LLMBackend(ABC):
    @abstractmethod
    def generate(
        self,
        *,
        system: Optional[str],
        text: str,
        images: List[bytes],
        response_schema: Optional[Dict],
        temperature: float = 0.0,
        seed: Optional[int] = None,
        prompt_id: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResult:
        """The vendor-neutral entry point."""

    @abstractmethod
    def generate_from_payload(self, payload_dir: str, model: str, max_tokens: int = 4096) -> LLMResult:
        """Convenience wrapper reading an llm/payload_builder.py output
        directory (prompt.txt, evidence_summary.json, screenshots/,
        response_schema.json, manifest.json) directly -- the shape every
        existing caller already has on disk."""


def read_payload(payload_dir: str) -> Tuple[str, str, Optional[Dict], List[str], str]:
    """Shared loader for generate_from_payload() implementations: returns
    (prompt_text, evidence_summary_text, response_schema_or_None,
    screenshot_paths_sorted, prompt_id). prompt_id is derived from
    manifest.json's role/attribute (e.g. "attribute/asymmetry",
    "coordinator") -- falls back to the payload_dir path if no manifest
    is present (should not happen for a real llm/payload_builder.py
    output, but this loader shouldn't crash on a hand-built test
    fixture that omits it)."""

    def _read(name: str) -> str:
        with open(os.path.join(payload_dir, name), "r", encoding="utf-8") as f:
            return f.read()

    prompt_text = _read("prompt.txt")
    evidence_summary_text = _read("evidence_summary.json")

    response_schema = None
    if os.path.isfile(os.path.join(payload_dir, "response_schema.json")):
        response_schema = json.loads(_read("response_schema.json"))

    screenshots_dir = os.path.join(payload_dir, "screenshots")
    screenshot_paths = []
    if os.path.isdir(screenshots_dir):
        screenshot_paths = [os.path.join(screenshots_dir, name) for name in sorted(os.listdir(screenshots_dir))]

    prompt_id = payload_dir
    manifest_path = os.path.join(payload_dir, "manifest.json")
    if os.path.isfile(manifest_path):
        manifest = json.loads(_read("manifest.json"))
        role = manifest.get("role")
        attribute = manifest.get("attribute")
        prompt_id = f"{role}/{attribute}" if attribute else role

    return prompt_text, evidence_summary_text, response_schema, screenshot_paths, prompt_id
