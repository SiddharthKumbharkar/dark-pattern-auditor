"""Posts to the TCS-hosted GPT-4o relay (server/app.py) through the
code-server proxy:

    POST {TCS_LLM_URL}/execute

TCS_LLM_URL is the FULL proxy base, e.g.
"https://rniazure.tcsapps.com/dev-workspaces/<workspace-id>/proxy/8000" --
this module only ever appends "/execute" to it, never constructs the
workspace-id/proxy path itself (that's TCS_LLM_URL's job, read from
env/.env -- see .env.example). Auth is a code-server-session cookie
(TCS_SESSION_COOKIE), never a bearer token, and is never logged.
"""

import json
import os
import time
from typing import Dict, List, Optional

import requests

from llm.backends.base import LLMBackend, LLMResult, read_payload
from llm.image_tiling import tile_screenshot

DEFAULT_TIMEOUT_SECONDS = 120.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_BASE_SECONDS = 2.0

_GENERIC_SYSTEM_MESSAGE = (
    "You are a precise auditing assistant. Respond only via the provided JSON schema."
)
_JSON_REPAIR_SUFFIX = (
    "\n\nYour previous reply could not be parsed as JSON matching the schema above. Reply "
    "again with ONLY valid JSON matching that schema -- no prose, no markdown fences."
)

# Public OpenAI API list price for gpt-4o, used ONLY to log an
# approximate cost alongside the real token counts every call already
# returns -- NOT necessarily this TCS deployment's actual billing rate
# (an Azure/enterprise agreement can differ). Confirm with whoever owns
# the workspace's billing before trusting estimated_cost_usd for a real
# budget decision; update this table if it drifts from published rates.
_PRICE_PER_MTOK_USD = {"gpt-4o": {"input": 2.50, "output": 10.00}}


class TcsBackendError(RuntimeError):
    """The TCS relay call failed for a reason that isn't session expiry --
    a non-timeout/non-5xx failure after transport retries are exhausted,
    or malformed JSON surviving the one repair retry."""


class TcsSessionExpiredError(TcsBackendError):
    """The proxy returned something other than the relay's own JSON (an
    HTML login page, typically) -- TCS_SESSION_COOKIE needs refreshing.
    Never retried: retrying with the same expired cookie can't succeed."""


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return float(raw) if raw else default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw else default


def _price_for_model(model: Optional[str]) -> Optional[Dict[str, float]]:
    if not model:
        return None
    for prefix, prices in _PRICE_PER_MTOK_USD.items():
        if model.startswith(prefix):
            return prices
    return None


def estimated_cost_usd(model: Optional[str], prompt_tokens: int, completion_tokens: int) -> Optional[float]:
    prices = _price_for_model(model)
    if not prices:
        return None
    cost = (prompt_tokens * prices["input"] + completion_tokens * prices["output"]) / 1_000_000
    return round(cost, 6)


class TCSGPT4oBackend(LLMBackend):
    def __init__(
        self,
        base_url: Optional[str] = None,
        session_cookie: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        max_retries: Optional[int] = None,
        session: Optional[object] = None,
    ):
        self._base_url = (base_url or os.environ.get("TCS_LLM_URL") or "").rstrip("/")
        self._cookie = session_cookie or os.environ.get("TCS_SESSION_COOKIE")
        self._timeout = (
            timeout_seconds if timeout_seconds is not None else _env_float("TCS_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)
        )
        self._max_retries = (
            max_retries if max_retries is not None else _env_int("TCS_MAX_RETRIES", DEFAULT_MAX_RETRIES)
        )
        # Injectable for tests -- must expose a requests-shaped
        # .post(url, data=, files=, cookies=, timeout=) -> Response.
        self._session = session or requests

        if not self._base_url:
            raise TcsBackendError("TCS_LLM_URL is not set -- see .env.example.")
        if not self._cookie:
            raise TcsBackendError("TCS_SESSION_COOKIE is not set -- see .env.example.")

    def _post(self, data: Dict, files: List) -> "requests.Response":
        url = f"{self._base_url}/execute"
        last_exc: Optional[Exception] = None
        for attempt in range(1, self._max_retries + 1):
            try:
                response = self._session.post(
                    url, data=data, files=files,
                    cookies={"code-server-session": self._cookie},
                    timeout=self._timeout,
                )
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_exc = exc
                if attempt < self._max_retries:
                    time.sleep(DEFAULT_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)))
                    continue
                raise TcsBackendError(f"TCS relay unreachable after {attempt} attempt(s): {exc}") from exc

            if response.status_code >= 500:
                last_exc = TcsBackendError(f"TCS relay returned {response.status_code}")
                if attempt < self._max_retries:
                    time.sleep(DEFAULT_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)))
                    continue
                raise last_exc

            return response  # 2xx/4xx: not retried -- caller interprets it (incl. session-expiry below)

        raise last_exc or TcsBackendError("TCS relay call failed for an unknown reason")

    def _parse_response(self, response: "requests.Response") -> Dict:
        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type:
            raise TcsSessionExpiredError(
                f"TCS relay did not return JSON (content-type={content_type!r}, status="
                f"{response.status_code}) -- this is what an expired code-server-session cookie "
                f"looks like (the proxy serves an HTML login page instead). Refresh "
                f"TCS_SESSION_COOKIE and retry."
            )
        try:
            return response.json()
        except ValueError as exc:
            raise TcsSessionExpiredError(
                f"TCS relay's response body wasn't valid JSON despite a JSON content-type "
                f"(status={response.status_code}) -- treating this the same as an expired "
                f"session. Refresh TCS_SESSION_COOKIE and retry. ({exc})"
            ) from exc

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
        data = {"prompt_id": prompt_id or "unlabeled", "text": text, "temperature": str(temperature)}
        if system:
            data["system"] = system
        if response_schema is not None:
            data["response_schema"] = json.dumps(response_schema)
        if seed is not None:
            data["seed"] = str(seed)
        if max_tokens is not None:
            data["max_tokens"] = str(max_tokens)

        files = [("images", (f"image_{i:03d}.png", img, "image/png")) for i, img in enumerate(images)]
        body = self._parse_response(self._post(data, files))

        if response_schema is not None and body.get("ok") and body.get("output_json") is None:
            # The server's own json_object fallback still produced
            # non-JSON text -- one repair retry, asking explicitly, then
            # give up loudly rather than silently returning garbage.
            repair_data = dict(data)
            repair_data["text"] = text + _JSON_REPAIR_SUFFIX
            body = self._parse_response(self._post(repair_data, files))
            if body.get("ok") and body.get("output_json") is None:
                return LLMResult(
                    ok=False, model=body.get("model"), request_id=body.get("request_id"),
                    error="TCS relay returned non-JSON output after one repair retry",
                )

        usage = body.get("usage") or {}
        return LLMResult(
            ok=bool(body.get("ok")),
            output_text=body.get("output_text", ""),
            output_json=body.get("output_json"),
            model=body.get("model"),
            system_fingerprint=body.get("system_fingerprint"),
            usage={
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
            },
            latency_ms=body.get("latency_ms"),
            request_id=body.get("request_id"),
            error=body.get("error"),
        )

    def generate_from_payload(self, payload_dir: str, model: str, max_tokens: int = 4096) -> LLMResult:
        """`model` is accepted for call-signature parity with
        AnthropicBackend/call_for_judgement, but NOT sent to the server --
        the TCS relay picks its own configured GPT-4o deployment (see
        server/openai_client.py); the actual model used comes back in
        LLMResult.model and is what gets logged/used for ingest
        provenance, not this argument."""
        prompt_text, evidence_summary_text, response_schema, screenshot_paths, prompt_id = read_payload(payload_dir)

        images: List[bytes] = []
        listing_lines: List[str] = []
        for path in screenshot_paths:
            with open(path, "rb") as f:
                raw = f.read()
            page_label = os.path.basename(path)
            for tile in tile_screenshot(raw):
                images.append(tile.png_bytes)
                position = len(images)
                if tile.total > 1:
                    listing_lines.append(
                        f"  image {position}: {page_label}, tile {tile.index + 1} of {tile.total} "
                        f"(y={tile.y_offset}-{tile.y_offset + tile.height})"
                    )
                else:
                    listing_lines.append(f"  image {position}: {page_label}")

        text = prompt_text + "\n\nevidence_summary.json:\n" + evidence_summary_text
        if listing_lines:
            text += "\n\nImages are attached in this exact order:\n" + "\n".join(listing_lines)

        result = self.generate(
            system=_GENERIC_SYSTEM_MESSAGE, text=text, images=images, response_schema=response_schema,
            max_tokens=max_tokens, prompt_id=prompt_id,
        )
        self._write_run_log(payload_dir, result)
        return result

    def _write_run_log(self, payload_dir: str, result: LLMResult) -> None:
        from llm.api_client import USAGE_LOG_FILENAME  # same filename as the Anthropic path, TCS-shaped contents

        prompt_tokens = result.usage.get("prompt_tokens", 0)
        completion_tokens = result.usage.get("completion_tokens", 0)
        log = {
            "backend": "tcs_gpt4o",
            "model": result.model,
            "system_fingerprint": result.system_fingerprint,
            "input_tokens": prompt_tokens,
            "output_tokens": completion_tokens,
            "latency_ms": result.latency_ms,
            "request_id": result.request_id,
            "ok": result.ok,
            "error": result.error,
            "estimated_cost_usd": estimated_cost_usd(result.model, prompt_tokens, completion_tokens),
        }
        with open(os.path.join(payload_dir, USAGE_LOG_FILENAME), "w", encoding="utf-8") as f:
            json.dump(log, f, indent=2)
