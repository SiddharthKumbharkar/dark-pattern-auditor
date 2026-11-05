"""No real OpenAI/Azure call is made here -- openai_client.complete is
monkeypatched, same hand-rolled-fake convention as the parent repo's own
tests/test_api_client.py (no HTTP-mocking library).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import openai_client  # noqa: E402
from app import app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(app)


def _fake_complete(ok=True, output_json=None, error=None, used_json_object_fallback=False, **_ignored):
    def _complete(**kwargs):
        return openai_client.CompletionResult(
            ok=ok,
            output_text="{}" if output_json is not None else "hello",
            output_json=output_json,
            model="gpt-4o-2024-08-06",
            system_fingerprint="fp_test123",
            prompt_tokens=42,
            completion_tokens=7,
            latency_ms=123.4,
            request_id="req_abc",
            error=error,
            used_json_object_fallback=used_json_object_fallback,
        )

    return _complete


def test_health_reports_not_configured_when_no_env_vars_set(monkeypatch):
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["configured"] is False
    assert body["backend"] == "not_configured"


def test_health_reports_openai_compatible_when_api_key_set(monkeypatch):
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o")
    resp = client.get("/health")
    body = resp.json()
    assert body["configured"] is True
    assert body["backend"] == "openai_compatible"
    assert body["model"] == "gpt-4o"


def test_execute_happy_path_relays_structured_output(monkeypatch):
    monkeypatch.setattr(openai_client, "complete", _fake_complete(output_json={"verdict": "fires"}))
    resp = client.post(
        "/execute",
        data={"prompt_id": "attribute/asymmetry", "text": "judge this", "response_schema": '{"type":"object"}'},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["output_json"] == {"verdict": "fires"}
    assert body["model"] == "gpt-4o-2024-08-06"
    assert body["usage"] == {"prompt_tokens": 42, "completion_tokens": 7}
    assert body["used_json_object_fallback"] is False


def test_execute_with_images(monkeypatch):
    captured = {}

    def _complete(**kwargs):
        captured.update(kwargs)
        return openai_client.CompletionResult(ok=True, output_text="ok")

    monkeypatch.setattr(openai_client, "complete", _complete)
    png_bytes = b"\x89PNG\r\n\x1a\nfake-png-bytes"
    resp = client.post(
        "/execute",
        data={"prompt_id": "triage", "text": "judge this"},
        files=[("images", ("step_001.png", png_bytes, "image/png"))],
    )
    assert resp.status_code == 200
    assert len(captured["images_b64"]) == 1


def test_execute_rejects_too_many_images(monkeypatch):
    import app as app_module

    monkeypatch.setattr(app_module, "MAX_IMAGES_PER_REQUEST", 1)
    files = [("images", (f"s{i}.png", b"x", "image/png")) for i in range(2)]
    resp = client.post("/execute", data={"prompt_id": "x", "text": "y"}, files=files)
    assert resp.status_code == 413


def test_execute_rejects_malformed_response_schema():
    resp = client.post(
        "/execute", data={"prompt_id": "x", "text": "y", "response_schema": "{not json"}
    )
    assert resp.status_code == 422


def test_execute_relays_model_side_error_as_ok_false(monkeypatch):
    monkeypatch.setattr(openai_client, "complete", _fake_complete(ok=False, error="RateLimitError: 429"))
    resp = client.post("/execute", data={"prompt_id": "x", "text": "y"})
    assert resp.status_code == 200  # structured error, not a bare 500
    body = resp.json()
    assert body["ok"] is False
    assert "RateLimitError" in body["error"]


def test_execute_returns_500_when_backend_not_configured(monkeypatch):
    def _raise(**kwargs):
        raise openai_client.BackendNotConfiguredError("neither env-var group set")

    monkeypatch.setattr(openai_client, "complete", _raise)
    resp = client.post("/execute", data={"prompt_id": "x", "text": "y"})
    assert resp.status_code == 500
