"""llm/api_client.py::call_for_judgement()'s backend dispatch -- see that
function's docstring. Verifies:
  - an explicitly-injected `client=` always takes the legacy Anthropic
    path, regardless of LLM_BACKEND (the existing test seam, untouched);
  - with no `client=`, LLM_BACKEND picks which backend handles the call;
  - a non-ok / no-output_json LLMResult from a non-Anthropic backend
    becomes an ApiCallError, same contract as the Anthropic path's own
    "no tool_use block" failure.

Builds a minimal, hand-written payload directory directly (role=
"coordinator", so the per-episode budget file sits one level up at
payload_dir's own parent -- see llm/api_client.py's _episode_level_dir())
rather than running the full recorder+build_payload pipeline, since
nothing here needs a real episode.
"""

import json

import pytest

from llm.api_client import ApiCallError, BudgetExceededError, call_for_judgement
from llm.backends.base import LLMResult


@pytest.fixture
def payload_dir(tmp_path):
    d = tmp_path / "payload" / "ep1" / "coordinator"
    d.mkdir(parents=True)
    (d / "prompt.txt").write_text("Coordinate this.", encoding="utf-8")
    (d / "evidence_summary.json").write_text(json.dumps({}), encoding="utf-8")
    (d / "response_schema.json").write_text(json.dumps({"type": "object"}), encoding="utf-8")
    (d / "manifest.json").write_text(json.dumps({"role": "coordinator", "episode_id": "ep1"}), encoding="utf-8")
    return str(d)


class _FakeBackend:
    def __init__(self, result):
        self._result = result
        self.calls = 0

    def generate_from_payload(self, payload_dir, model, max_tokens=4096):
        self.calls += 1
        return self._result


def test_no_client_dispatches_through_get_backend(monkeypatch, payload_dir):
    monkeypatch.setenv("LLM_BACKEND", "tcs_gpt4o")
    fake = _FakeBackend(LLMResult(ok=True, output_json={"pattern_combinations": []}))
    monkeypatch.setattr("llm.backends.factory.get_backend", lambda name=None: fake)

    result = call_for_judgement(payload_dir, model="gpt-4o")

    assert result == {"pattern_combinations": []}
    assert fake.calls == 1


def test_backend_not_ok_becomes_api_call_error(monkeypatch, payload_dir):
    monkeypatch.setenv("LLM_BACKEND", "tcs_gpt4o")
    fake = _FakeBackend(LLMResult(ok=False, error="RateLimitError: 429"))
    monkeypatch.setattr("llm.backends.factory.get_backend", lambda name=None: fake)

    with pytest.raises(ApiCallError, match="RateLimitError"):
        call_for_judgement(payload_dir, model="gpt-4o")


def test_backend_ok_but_no_output_json_becomes_api_call_error(monkeypatch, payload_dir):
    monkeypatch.setenv("LLM_BACKEND", "tcs_gpt4o")
    fake = _FakeBackend(LLMResult(ok=True, output_json=None))
    monkeypatch.setattr("llm.backends.factory.get_backend", lambda name=None: fake)

    with pytest.raises(ApiCallError, match="no parsed JSON"):
        call_for_judgement(payload_dir, model="gpt-4o")


def test_explicit_client_bypasses_backend_dispatch_even_with_tcs_default(monkeypatch, payload_dir):
    """The existing test seam (tests/test_api_client.py's
    _FakeAnthropicClient) must keep working unchanged no matter what
    LLM_BACKEND resolves to -- an explicitly-injected client always means
    "use it as an Anthropic client", per call_for_judgement()'s docstring."""
    monkeypatch.setenv("LLM_BACKEND", "tcs_gpt4o")

    # If dispatch were (wrongly) routed through get_backend() here, this
    # would be called instead of the injected client -- it must not be.
    def _fail_if_called(name=None):
        raise AssertionError("get_backend() must not be called when client= is explicitly given")

    monkeypatch.setattr("llm.backends.factory.get_backend", _fail_if_called)

    class _FakeUsage:
        input_tokens = 10
        output_tokens = 5
        cache_creation_input_tokens = 0
        cache_read_input_tokens = 0

    class _FakeToolUseBlock:
        type = "tool_use"
        input = {"pattern_combinations": []}

    class _FakeMessage:
        content = [_FakeToolUseBlock()]
        usage = _FakeUsage()
        stop_reason = "tool_use"

    class _FakeMessagesResource:
        def create(self, **kwargs):
            return _FakeMessage()

    class _FakeAnthropicClient:
        messages = _FakeMessagesResource()

    result = call_for_judgement(payload_dir, model="claude-sonnet-5", client=_FakeAnthropicClient())
    assert result == {"pattern_combinations": []}


def test_budget_is_enforced_before_backend_dispatch(monkeypatch, payload_dir):
    monkeypatch.setenv("LLM_BACKEND", "tcs_gpt4o")
    fake = _FakeBackend(LLMResult(ok=True, output_json={}))
    monkeypatch.setattr("llm.backends.factory.get_backend", lambda name=None: fake)

    call_for_judgement(payload_dir, model="gpt-4o", max_calls=1)
    with pytest.raises(BudgetExceededError):
        call_for_judgement(payload_dir, model="gpt-4o", max_calls=1)
    assert fake.calls == 1  # the second call never reached the backend
