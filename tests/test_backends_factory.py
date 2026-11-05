import pytest

from llm.backends.anthropic_backend import AnthropicBackend
from llm.backends.factory import DEFAULT_BACKEND, get_backend, preflight_message, resolve_backend_name
from llm.backends.tcs_gpt4o_backend import TCSGPT4oBackend


def test_default_backend_is_tcs_gpt4o(monkeypatch):
    monkeypatch.delenv("LLM_BACKEND", raising=False)
    assert DEFAULT_BACKEND == "tcs_gpt4o"
    assert resolve_backend_name() == "tcs_gpt4o"


def test_llm_backend_env_var_overrides_the_default(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "anthropic")
    assert resolve_backend_name() == "anthropic"


def test_get_backend_tcs_gpt4o(monkeypatch):
    monkeypatch.setenv("TCS_LLM_URL", "https://example.tcsapps.com/proxy/8000")
    monkeypatch.setenv("TCS_SESSION_COOKIE", "fake-cookie")
    backend = get_backend("tcs_gpt4o")
    assert isinstance(backend, TCSGPT4oBackend)


def test_get_backend_anthropic():
    backend = get_backend("anthropic")
    assert isinstance(backend, AnthropicBackend)


def test_get_backend_rejects_unknown_name():
    with pytest.raises(ValueError, match="Unknown LLM_BACKEND"):
        get_backend("ollama")  # not implemented (yet) -- see factory.py's docstring


# -- preflight_message --------------------------------------------------------


def test_preflight_message_anthropic_missing_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert "ANTHROPIC_API_KEY" in preflight_message("anthropic")


def test_preflight_message_anthropic_key_present(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
    assert preflight_message("anthropic") is None


def test_preflight_message_tcs_missing_both(monkeypatch):
    monkeypatch.delenv("TCS_LLM_URL", raising=False)
    monkeypatch.delenv("TCS_SESSION_COOKIE", raising=False)
    message = preflight_message("tcs_gpt4o")
    assert "TCS_LLM_URL" in message and "TCS_SESSION_COOKIE" in message


def test_preflight_message_tcs_missing_one(monkeypatch):
    monkeypatch.setenv("TCS_LLM_URL", "https://example.tcsapps.com/proxy/8000")
    monkeypatch.delenv("TCS_SESSION_COOKIE", raising=False)
    message = preflight_message("tcs_gpt4o")
    assert message == "TCS_SESSION_COOKIE is not set. Add to .env at the project root (see .env.example)."


def test_preflight_message_tcs_both_present(monkeypatch):
    monkeypatch.setenv("TCS_LLM_URL", "https://example.tcsapps.com/proxy/8000")
    monkeypatch.setenv("TCS_SESSION_COOKIE", "fake-cookie")
    assert preflight_message("tcs_gpt4o") is None


def test_preflight_message_unknown_backend():
    assert "Unknown LLM_BACKEND" in preflight_message("ollama")
