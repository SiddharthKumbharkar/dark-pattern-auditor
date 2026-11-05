"""Adapter exposing llm/api_client.py's existing, fully-tested Anthropic
call path through the generic LLMBackend interface. Does NOT reimplement
build_messages/response_schema_to_tool/the image-budget logic -- imports
and reuses llm/api_client.py's own directly, so there is exactly one
implementation of "how Claude sees a payload directory" in this codebase.

llm/api_client.py's own call_for_judgement() does NOT route through this
class when an Anthropic client is explicitly injected (the existing
tests' seam, see that function's docstring) -- that exact code path is
preserved untouched, including its own usage.json shape (with Anthropic-
specific cache_read/cache_creation token fields). This class is what
LLM_BACKEND=anthropic resolves to for any OTHER caller (a future
taxonomy-profile judge call going through the vendor-neutral interface
directly, or get_backend() used outside call_for_judgement).
"""

import base64
from typing import Dict, List, Optional

from llm.backends.base import LLMBackend, LLMResult, read_payload

_DEFAULT_MODEL = "claude-sonnet-5"


class AnthropicBackend(LLMBackend):
    def __init__(self, client: Optional[object] = None, model: str = _DEFAULT_MODEL):
        self._client = client
        self._model = model

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
        import anthropic

        from llm.api_client import _TOOL_NAME, response_schema_to_tool

        content: List[Dict] = []
        if system:
            # This codebase's existing Anthropic convention has no system-
            # message slot at all (see build_messages()'s docstring) --
            # prepended as its own text block instead of being dropped,
            # so this adapter still behaves sensibly if a future caller
            # passes one.
            content.append({"type": "text", "text": system})
        content.append({"type": "text", "text": text})
        for image_bytes in images:
            content.append({
                "type": "image",
                "source": {
                    "type": "base64", "media_type": "image/png",
                    "data": base64.standard_b64encode(image_bytes).decode("ascii"),
                },
            })
        messages = [{"role": "user", "content": content}]

        kwargs: Dict = {"model": self._model, "max_tokens": max_tokens or 4096, "messages": messages}
        if response_schema:
            tool = response_schema_to_tool(response_schema)
            kwargs["tools"] = [tool]
            kwargs["tool_choice"] = {"type": "tool", "name": _TOOL_NAME}

        client = self._client or anthropic.Anthropic()
        message = client.messages.create(**kwargs)

        usage = getattr(message, "usage", None)
        input_tokens = getattr(usage, "input_tokens", 0) or 0
        output_tokens = getattr(usage, "output_tokens", 0) or 0

        output_json = None
        output_text = ""
        if response_schema:
            tool_uses = [b for b in message.content if getattr(b, "type", None) == "tool_use"]
            if tool_uses:
                output_json = tool_uses[0].input
        else:
            output_text = "".join(
                getattr(b, "text", "") for b in message.content if getattr(b, "type", None) == "text"
            )

        ok = (output_json is not None) if response_schema else True
        return LLMResult(
            ok=ok,
            output_text=output_text,
            output_json=output_json,
            model=getattr(message, "model", self._model),
            system_fingerprint=None,  # Anthropic's Messages API doesn't return one
            usage={"prompt_tokens": input_tokens, "completion_tokens": output_tokens},
            request_id=getattr(message, "id", None),
            error=None if ok else (
                f"model did not return the forced tool call -- stop_reason="
                f"{getattr(message, 'stop_reason', None)!r}"
            ),
        )

    def generate_from_payload(self, payload_dir: str, model: str, max_tokens: int = 4096) -> LLMResult:
        prompt_text, evidence_summary_text, response_schema, screenshot_paths, prompt_id = read_payload(payload_dir)
        self._model = model
        text = prompt_text + "\n\nevidence_summary.json:\n" + evidence_summary_text
        images = []
        for path in screenshot_paths:
            with open(path, "rb") as f:
                images.append(f.read())
        return self.generate(
            system=None, text=text, images=images, response_schema=response_schema,
            max_tokens=max_tokens, prompt_id=prompt_id,
        )
