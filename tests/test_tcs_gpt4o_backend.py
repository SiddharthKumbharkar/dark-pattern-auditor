"""llm/backends/tcs_gpt4o_backend.py -- the TCS relay HTTP client. Same
hand-rolled-fake convention as tests/test_api_client.py's
_FakeAnthropicClient (no HTTP-mocking library): a fake `session` object
shaped like `requests`' own `.post(...)` is injected via the backend's
`session=` constructor param, so no real network call is ever made.
"""

import json
import os

import pytest
import requests

from llm.backends.base import LLMResult
from llm.backends.tcs_gpt4o_backend import (
    TCSGPT4oBackend,
    TcsBackendError,
    TcsSessionExpiredError,
    estimated_cost_usd,
)


class _FakeResponse:
    def __init__(self, status_code=200, json_body=None, content_type="application/json"):
        self.status_code = status_code
        self._json_body = json_body
        self.headers = {"content-type": content_type}

    def json(self):
        if self._json_body is None:
            raise ValueError("no JSON body on this fake response")
        return self._json_body


class _FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def post(self, url, data=None, files=None, cookies=None, timeout=None):
        self.calls.append({"url": url, "data": data, "files": files, "cookies": cookies, "timeout": timeout})
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _backend(session, **overrides):
    kwargs = dict(
        base_url="https://rniazure.tcsapps.com/dev-workspaces/ws-123/proxy/8000",
        session_cookie="fake-session-cookie",
        max_retries=3,
        timeout_seconds=5.0,
        session=session,
    )
    kwargs.update(overrides)
    return TCSGPT4oBackend(**kwargs)


def _ok_body(output_json=None, model="gpt-4o-2024-08-06"):
    return {
        "ok": True,
        "output_text": json.dumps(output_json) if output_json is not None else "hello",
        "output_json": output_json,
        "model": model,
        "system_fingerprint": "fp_test",
        "usage": {"prompt_tokens": 1000, "completion_tokens": 50},
        "latency_ms": 321.0,
        "request_id": "req_abc",
        "error": None,
    }


# -- construction / env wiring -----------------------------------------------


def test_missing_base_url_raises_immediately(monkeypatch):
    monkeypatch.delenv("TCS_LLM_URL", raising=False)
    with pytest.raises(TcsBackendError, match="TCS_LLM_URL"):
        TCSGPT4oBackend(session_cookie="x")


def test_missing_cookie_raises_immediately(monkeypatch):
    monkeypatch.delenv("TCS_SESSION_COOKIE", raising=False)
    with pytest.raises(TcsBackendError, match="TCS_SESSION_COOKIE"):
        TCSGPT4oBackend(base_url="https://example.tcsapps.com/proxy/8000")


def test_reads_base_url_and_cookie_from_env(monkeypatch):
    monkeypatch.setenv("TCS_LLM_URL", "https://example.tcsapps.com/proxy/8000")
    monkeypatch.setenv("TCS_SESSION_COOKIE", "cookie-from-env")
    backend = TCSGPT4oBackend(session=_FakeSession([_FakeResponse(json_body=_ok_body())]))
    result = backend.generate(system=None, text="hi", images=[], response_schema=None)
    assert result.ok is True


# -- happy path ---------------------------------------------------------------


def test_happy_path_posts_to_execute_with_cookie_and_returns_llm_result():
    session = _FakeSession([_FakeResponse(json_body=_ok_body(output_json={"verdict": "fires"}))])
    backend = _backend(session)

    result = backend.generate(
        system="be precise", text="judge this", images=[b"png-bytes"],
        response_schema={"type": "object"}, prompt_id="attribute/asymmetry",
    )

    assert isinstance(result, LLMResult)
    assert result.ok is True
    assert result.output_json == {"verdict": "fires"}
    assert result.model == "gpt-4o-2024-08-06"
    assert result.usage == {"prompt_tokens": 1000, "completion_tokens": 50}

    assert len(session.calls) == 1
    call = session.calls[0]
    assert call["url"] == "https://rniazure.tcsapps.com/dev-workspaces/ws-123/proxy/8000/execute"
    assert call["cookies"] == {"code-server-session": "fake-session-cookie"}
    assert call["data"]["prompt_id"] == "attribute/asymmetry"
    assert call["data"]["system"] == "be precise"
    assert json.loads(call["data"]["response_schema"]) == {"type": "object"}
    assert call["files"] == [("images", ("image_000.png", b"png-bytes", "image/png"))]


def test_cookie_is_never_included_in_any_exception_message():
    session = _FakeSession([requests.Timeout("timed out")] * 5)
    backend = _backend(session, max_retries=2, session_cookie="super-secret-cookie-value")
    with pytest.raises(TcsBackendError) as exc_info:
        backend.generate(system=None, text="x", images=[], response_schema=None)
    assert "super-secret-cookie-value" not in str(exc_info.value)


# -- session-expired detection ------------------------------------------------


def test_html_response_is_treated_as_an_expired_session():
    session = _FakeSession([_FakeResponse(status_code=200, content_type="text/html; charset=utf-8")])
    backend = _backend(session)
    with pytest.raises(TcsSessionExpiredError, match="TCS_SESSION_COOKIE"):
        backend.generate(system=None, text="x", images=[], response_schema=None)
    assert len(session.calls) == 1  # never retried -- a fresh attempt with the same cookie can't help


def test_json_content_type_but_unparseable_body_is_also_treated_as_expired():
    class _BrokenJsonResponse(_FakeResponse):
        def json(self):
            raise ValueError("Expecting value: line 1 column 1 (char 0)")

    session = _FakeSession([_BrokenJsonResponse(content_type="application/json")])
    backend = _backend(session)
    with pytest.raises(TcsSessionExpiredError):
        backend.generate(system=None, text="x", images=[], response_schema=None)


# -- retries: timeouts and 5xx only ------------------------------------------


def test_timeout_is_retried_up_to_max_retries_then_raises(monkeypatch):
    monkeypatch.setattr("llm.backends.tcs_gpt4o_backend.DEFAULT_BACKOFF_BASE_SECONDS", 0)
    session = _FakeSession([requests.Timeout("t1"), requests.Timeout("t2"), requests.Timeout("t3")])
    backend = _backend(session, max_retries=3)
    with pytest.raises(TcsBackendError, match="unreachable"):
        backend.generate(system=None, text="x", images=[], response_schema=None)
    assert len(session.calls) == 3


def test_timeout_succeeds_on_a_later_attempt(monkeypatch):
    monkeypatch.setattr("llm.backends.tcs_gpt4o_backend.DEFAULT_BACKOFF_BASE_SECONDS", 0)
    session = _FakeSession([requests.Timeout("t1"), _FakeResponse(json_body=_ok_body())])
    backend = _backend(session, max_retries=3)
    result = backend.generate(system=None, text="x", images=[], response_schema=None)
    assert result.ok is True
    assert len(session.calls) == 2


def test_5xx_is_retried_then_raises_if_never_recovers(monkeypatch):
    monkeypatch.setattr("llm.backends.tcs_gpt4o_backend.DEFAULT_BACKOFF_BASE_SECONDS", 0)
    session = _FakeSession([_FakeResponse(status_code=502), _FakeResponse(status_code=503)])
    backend = _backend(session, max_retries=2)
    with pytest.raises(TcsBackendError, match="502|503"):
        backend.generate(system=None, text="x", images=[], response_schema=None)
    assert len(session.calls) == 2


def test_4xx_is_never_retried():
    session = _FakeSession([_FakeResponse(status_code=422, json_body={"detail": "bad request"})])
    backend = _backend(session, max_retries=3)
    # A 422 with a JSON body still reaches _parse_response -- it's not a
    # transport failure, so the backend hands it back as-is (ok defaults
    # falsy since this fake body has no "ok" key) rather than retrying.
    result = backend.generate(system=None, text="x", images=[], response_schema=None)
    assert result.ok is False
    assert len(session.calls) == 1


# -- malformed JSON: one repair retry, then fail loudly ----------------------


def test_malformed_json_triggers_one_repair_retry_that_succeeds():
    session = _FakeSession([
        _FakeResponse(json_body=_ok_body(output_json=None)),  # server's own fallback still non-JSON
        _FakeResponse(json_body=_ok_body(output_json={"verdict": "no"})),  # repair retry succeeds
    ])
    backend = _backend(session)
    result = backend.generate(system=None, text="judge this", images=[], response_schema={"type": "object"})
    assert result.ok is True
    assert result.output_json == {"verdict": "no"}
    assert len(session.calls) == 2
    assert "could not be parsed as JSON" in session.calls[1]["data"]["text"]


def test_malformed_json_after_repair_retry_fails_loudly():
    session = _FakeSession([
        _FakeResponse(json_body=_ok_body(output_json=None)),
        _FakeResponse(json_body=_ok_body(output_json=None)),
    ])
    backend = _backend(session)
    result = backend.generate(system=None, text="judge this", images=[], response_schema={"type": "object"})
    assert result.ok is False
    assert "repair retry" in result.error
    assert len(session.calls) == 2


def test_no_repair_retry_when_no_response_schema_was_requested():
    session = _FakeSession([_FakeResponse(json_body=_ok_body(output_json=None))])
    backend = _backend(session)
    backend.generate(system=None, text="free text is fine", images=[], response_schema=None)
    assert len(session.calls) == 1  # no schema requested -- a None output_json is not an error here


# -- model-side error (ok: false) relayed as LLMResult, not raised -----------


def test_model_side_error_is_relayed_as_llm_result_not_raised():
    session = _FakeSession([_FakeResponse(json_body={"ok": False, "error": "RateLimitError: 429", "usage": {}})])
    backend = _backend(session)
    result = backend.generate(system=None, text="x", images=[], response_schema=None)
    assert result.ok is False
    assert "RateLimitError" in result.error


# -- cost estimate ------------------------------------------------------------


def test_estimated_cost_usd_known_model():
    cost = estimated_cost_usd("gpt-4o-2024-08-06", prompt_tokens=1_000_000, completion_tokens=0)
    assert cost == 2.50


def test_estimated_cost_usd_unknown_model_is_none():
    assert estimated_cost_usd("some-future-model", 1000, 1000) is None


# -- generate_from_payload: reads payload_dir, tiles, writes usage.json ------


@pytest.fixture
def payload_dir(tmp_path):
    from PIL import Image

    d = tmp_path / "payload" / "ep1" / "attribute" / "asymmetry"
    (d / "screenshots").mkdir(parents=True)
    (d / "prompt.txt").write_text("Judge this attribute.", encoding="utf-8")
    (d / "evidence_summary.json").write_text(json.dumps({"attribute": "asymmetry"}), encoding="utf-8")
    (d / "response_schema.json").write_text(json.dumps({"type": "object"}), encoding="utf-8")
    (d / "manifest.json").write_text(
        json.dumps({"role": "attribute", "attribute": "asymmetry", "episode_id": "ep1"}), encoding="utf-8"
    )
    # A short screenshot (no tiling needed) and a tall one (tiled into 2+).
    Image.new("RGB", (800, 600), color="white").save(d / "screenshots" / "step_001.png")
    Image.new("RGB", (800, 4200), color="white").save(d / "screenshots" / "step_002.png")
    return str(d)


def test_generate_from_payload_labels_tiles_in_the_text_and_preserves_order(payload_dir):
    captured = {}

    def _complete(**kwargs):
        captured.update(kwargs)
        return _ok_body(output_json={"attribute": "asymmetry", "verdict": "no"})

    session = _FakeSession([_FakeResponse(json_body=_ok_body(output_json={"attribute": "asymmetry", "verdict": "no"}))])
    backend = _backend(session)

    result = backend.generate_from_payload(payload_dir, model="gpt-4o")
    assert result.ok is True

    sent_text = session.calls[0]["data"]["text"]
    assert "step_001.png" in sent_text
    assert "step_002.png, tile 1 of" in sent_text
    assert "Judge this attribute." in sent_text

    files = session.calls[0]["files"]
    assert len(files) >= 3  # 1 untiled + at least 2 tiles for the tall one
    assert session.calls[0]["data"]["prompt_id"] == "attribute/asymmetry"
    assert session.calls[0]["data"]["system"]  # the generic system message was sent


def test_generate_from_payload_writes_usage_json(payload_dir):
    session = _FakeSession([_FakeResponse(json_body=_ok_body(output_json={"attribute": "asymmetry", "verdict": "no"}))])
    backend = _backend(session)
    backend.generate_from_payload(payload_dir, model="gpt-4o")

    usage_path = os.path.join(payload_dir, "usage.json")
    assert os.path.isfile(usage_path)
    logged = json.load(open(usage_path, encoding="utf-8"))
    assert logged["backend"] == "tcs_gpt4o"
    assert logged["model"] == "gpt-4o-2024-08-06"
    assert logged["input_tokens"] == 1000
    assert logged["output_tokens"] == 50
    assert logged["estimated_cost_usd"] == pytest.approx(1000 * 2.50 / 1_000_000 + 50 * 10.00 / 1_000_000)
