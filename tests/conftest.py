"""Suite-wide safety net: block every real Anthropic API call AND every
real HTTP call to the TCS relay during tests, no matter which test file
or fixture is running.

The Anthropic guard exists because of a real incident: a test intended
to simulate "no ANTHROPIC_API_KEY" (tests/test_auto_audit.py) monkeypatched
the key out of os.environ, but auto_audit.main()'s own load_dotenv() call
re-populated it from this developer machine's real .env file once a real
key was added there -- so the test silently fell through to making real,
billed API calls during an ordinary `pytest` run. Fixed at both call
sites (stubbing dotenv.load_dotenv in the affected tests), but a single
environment-level key change should never be able to make the test suite
spend real money again, regardless of any one test's own care -- hence
this autouse guard, not just the point fixes. The same reasoning applies
to TCS_LLM_URL/TCS_SESSION_COOKIE now that LLM_BACKEND defaults to
"tcs_gpt4o" -- added proactively, same shape, before any equivalent
incident rather than after one.

No test in this suite is meant to call a real LLM API (see
llm/api_client.py's module docstring: the live call is verified manually,
not in the automated suite), so this should never need a per-test opt-out.
"""

import pytest


@pytest.fixture(autouse=True)
def _block_real_anthropic_api_calls(monkeypatch):
    def _blocked(*args, **kwargs):
        raise RuntimeError(
            "A test tried to make a real Anthropic API call. This is blocked suite-wide "
            "(tests/conftest.py) -- no test in this project's automated suite should ever "
            "call the real API (see llm/api_client.py's module docstring). If a test needs "
            "to exercise call_for_judgement()'s own logic, pass it a fake `client` object "
            "instead of relying on a real anthropic.Anthropic() instance."
        )

    monkeypatch.setattr("anthropic.resources.messages.Messages.create", _blocked)


@pytest.fixture(autouse=True)
def _block_real_tcs_relay_calls(monkeypatch):
    """TCSGPT4oBackend takes an injectable `session=` (same seam the
    Anthropic client= injection uses) specifically so no test needs this
    guard lifted -- see tests/test_tcs_gpt4o_backend.py's _FakeSession."""

    def _blocked(*args, **kwargs):
        raise RuntimeError(
            "A test tried to make a real HTTP call via requests.Session.request (or "
            "requests.post, which routes through it). This is blocked suite-wide "
            "(tests/conftest.py) so a stray real TCS_LLM_URL/TCS_SESSION_COOKIE can never make "
            "the test suite call the real TCS relay. Pass TCSGPT4oBackend a fake `session=` "
            "object instead -- see tests/test_tcs_gpt4o_backend.py's _FakeSession."
        )

    monkeypatch.setattr("requests.sessions.Session.request", _blocked)
