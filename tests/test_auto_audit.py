"""auto_audit.py -- the fully automated post-recording pipeline. Only the
--dry-run path and the missing-API-key guard are exercised here (real
network calls need a real key and spend real money, see
llm/api_client.py's docstring); this confirms the orchestration itself
(extract-evidence -> run-attributes -> payload construction for all 7
attributes + coordinator) actually runs end to end against a real recorded
episode, no mocks.
"""

import json
import os

import pytest

import auto_audit
from config.settings import Config
from journey.schema_migration import load_episode
from recorder.interactive_v2 import EPISODE_FILENAME, InteractiveRecorderV2

SIGNUP_HTML = """<!DOCTYPE html>
<html><body>
<h1>Create your account</h1>
<button id="accept-btn" type="button"
  style="background:#000;color:#fff;font-size:20px;padding:14px;">Yes, sign me up</button>
<button id="reject-btn" type="button"
  style="background:#f5f5f5;color:#f0f0f0;font-size:8px;padding:2px;">No thanks</button>
</body></html>
"""


@pytest.fixture
def site_dir(tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    (site / "signup.html").write_text(SIGNUP_HTML, encoding="utf-8")
    return site


@pytest.fixture
def episode_dir(tmp_path, site_dir):
    storage_dir = str(tmp_path / "storage")
    rec = InteractiveRecorderV2(
        storage_dir=storage_dir, episode_id="episode_auto_audit_test",
        site_url=(site_dir / "signup.html").as_uri(), site_domain="auto-audit-test.local",
        sector="ecommerce", goal_id="complete_signup", goal_description="auto_audit test",
        operator="test-operator", config=Config(),
    )
    rec.launch(headless=True)
    try:
        rec._poll_tick()
    finally:
        rec._teardown_browser()
        rec._cleanup_raw_artifacts()
    rec.finalize()
    return rec.episode_dir, storage_dir


def _config_path(tmp_path, storage_dir, payload_root):
    # A minimal config.yaml pointing output.root/payload.root at this
    # test's own tmp_path, so build_payload doesn't write into the real
    # repo's storage/ or payload/ directories.
    path = tmp_path / "config.yaml"
    path.write_text(
        f"output:\n  root: {storage_dir}\npayload:\n  root: {payload_root}\n", encoding="utf-8"
    )
    return str(path)


def test_missing_api_key_fails_before_touching_anything(monkeypatch, tmp_path, episode_dir):
    episode_path, storage_dir = episode_dir
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # auto_audit.main()'s own load_dotenv() would otherwise re-populate the
    # key from this developer machine's real .env file, defeating the "key
    # is genuinely absent" scenario this test needs -- stub it out. Without
    # this, this test silently makes real, paid API calls once a real key
    # exists in .env (found the hard way -- see tests/test_record_auto_audit.py).
    monkeypatch.setattr(auto_audit, "load_dotenv", lambda *a, **k: None)
    payload_root = str(tmp_path / "payload")
    cfg_path = _config_path(tmp_path, storage_dir, payload_root)

    before = load_episode(os.path.join(episode_path, EPISODE_FILENAME))
    assert not before.get("evidence")

    exit_code = auto_audit.main([episode_path, "--config", cfg_path])
    assert exit_code == 1

    after = load_episode(os.path.join(episode_path, EPISODE_FILENAME))
    assert not after.get("evidence")  # nothing ran -- guard fired before extract-evidence


def test_dry_run_builds_all_8_payloads_without_an_api_key(monkeypatch, tmp_path, episode_dir):
    episode_path, storage_dir = episode_dir
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(auto_audit, "load_dotenv", lambda *a, **k: None)  # keep this test key-free even with a real .env
    payload_root = str(tmp_path / "payload")
    cfg_path = _config_path(tmp_path, storage_dir, payload_root)

    exit_code = auto_audit.main([episode_path, "--dry-run", "--config", cfg_path])
    assert exit_code == 0

    # extract-evidence and run-attributes really ran (not skipped)
    episode = load_episode(os.path.join(episode_path, EPISODE_FILENAME))
    assert episode.get("evidence")
    assert len(episode["attributes"]["results"]) == 7

    # a payload directory was written for all 7 attributes + coordinator
    episode_id = "episode_auto_audit_test"
    for attribute in ("asymmetry", "covertness", "deception", "information_hiding", "restriction", "disparate_treatment", "complexity"):
        assert os.path.isfile(os.path.join(payload_root, episode_id, "attribute", attribute, "prompt.txt"))
    assert os.path.isfile(os.path.join(payload_root, episode_id, "coordinator", "prompt.txt"))

    # dry run must never write a response.json anywhere (no API call made)
    for attribute in ("asymmetry", "covertness", "deception", "information_hiding", "restriction", "disparate_treatment", "complexity"):
        assert not os.path.isfile(os.path.join(payload_root, episode_id, "attribute", attribute, "response.json"))
    assert not os.path.isfile(os.path.join(payload_root, episode_id, "coordinator", "response.json"))

    # dry run must never write mechanism_verdict.computed_output or report.html
    assert not (episode.get("mechanism_verdict") or {}).get("computed_output")
    assert not os.path.isfile(os.path.join(episode_path, "report.html"))


# -- retry on a rejected/failed Stage-2 response ----------------------------


def _real_payload_dir(tmp_path, episode_dir, attribute="asymmetry"):
    """extract-evidence + run-attributes for real, then build a real
    payload directory for one attribute -- everything _run_stage2_call
    needs except the (faked, no network) API call itself."""
    from journey.attribute_runner import run_attributes
    from journey.evidence_extractor import extract_evidence
    from llm.payload_builder import build_payload

    episode_path, storage_dir = episode_dir
    extract_evidence(episode_path)
    run_attributes(episode_path, storage_dir=storage_dir)
    payload_root = str(tmp_path / "payload")
    manifest = build_payload(episode_path, role="attribute", attribute=attribute, storage_dir=storage_dir, payload_root=payload_root)
    return episode_path, storage_dir, payload_root, manifest["payload_dir"]


def test_retries_a_rejected_response_and_succeeds_on_the_second_attempt(monkeypatch, tmp_path, episode_dir):
    episode_path, storage_dir, payload_root, payload_dir = _real_payload_dir(tmp_path, episode_dir)

    calls = {"judge": 0, "ingest": 0}

    def _fake_call_for_judgement(pd, model, max_calls=None):
        calls["judge"] += 1
        return {"attribute": "asymmetry", "verdict": "no", "severity": None, "confidence": 0.5, "evidence_pointers": [], "reasoning": "x"}

    def _fake_ingest_response(*args, **kwargs):
        calls["ingest"] += 1
        if calls["ingest"] == 1:
            raise auto_audit.IngestError(["simulated grounding rejection"])
        return {}

    monkeypatch.setattr(auto_audit, "call_for_judgement", _fake_call_for_judgement)
    monkeypatch.setattr(auto_audit, "ingest_response", _fake_ingest_response)

    result = auto_audit._run_stage2_call(
        episode_path, "attribute", "asymmetry", "claude-sonnet-5", "test-operator",
        storage_dir, payload_root, dry_run=False, max_attempts=2,
    )

    assert result is True
    assert calls["judge"] == 2  # first attempt's response was rejected, so a fresh one was requested
    assert calls["ingest"] == 2


def test_gives_up_after_max_attempts_and_returns_false(monkeypatch, tmp_path, episode_dir):
    episode_path, storage_dir, payload_root, payload_dir = _real_payload_dir(tmp_path, episode_dir)

    calls = {"judge": 0}

    def _fake_call_for_judgement(pd, model, max_calls=None):
        calls["judge"] += 1
        return {"attribute": "asymmetry", "verdict": "no", "severity": None, "confidence": 0.5, "evidence_pointers": [], "reasoning": "x"}

    def _always_rejects(*args, **kwargs):
        raise auto_audit.IngestError(["simulated grounding rejection"])

    monkeypatch.setattr(auto_audit, "call_for_judgement", _fake_call_for_judgement)
    monkeypatch.setattr(auto_audit, "ingest_response", _always_rejects)

    result = auto_audit._run_stage2_call(
        episode_path, "attribute", "asymmetry", "claude-sonnet-5", "test-operator",
        storage_dir, payload_root, dry_run=False, max_attempts=3,
    )

    assert result is False
    assert calls["judge"] == 3  # exactly max_attempts, no more


# -- per-episode LLM call budget: enforced INSIDE call_for_judgement() ------
#
# The budget itself (BudgetExceededError, the persistent per-episode call
# count) lives in llm/api_client.py now, not here -- see
# tests/test_api_client.py for the real enforcement tests (a direct
# call_for_judgement() path, no auto_audit.py involved at all, matching the
# actual gap this closed: a manual/direct caller used to bypass the cap
# entirely). What's left to verify at THIS layer is just the wiring: that
# --max-llm-calls actually reaches call_for_judgement(), and that a
# BudgetExceededError raised from inside it propagates out of
# _run_stage2_call() as a hard stop rather than being swallowed by the
# generic `except Exception` retry/continue path.


def test_max_llm_calls_is_passed_through_to_call_for_judgement(monkeypatch, tmp_path, episode_dir):
    episode_path, storage_dir, payload_root, payload_dir = _real_payload_dir(tmp_path, episode_dir)

    seen = {}

    def _fake_call_for_judgement(pd, model, max_calls=None):
        seen["max_calls"] = max_calls
        return {"attribute": "asymmetry", "verdict": "no", "severity": None, "confidence": 0.5, "evidence_pointers": [], "reasoning": "x"}

    monkeypatch.setattr(auto_audit, "call_for_judgement", _fake_call_for_judgement)
    monkeypatch.setattr(auto_audit, "ingest_response", lambda *a, **k: {})

    auto_audit._run_stage2_call(
        episode_path, "attribute", "asymmetry", "claude-sonnet-5", "test-operator",
        storage_dir, payload_root, dry_run=False, max_attempts=1, max_llm_calls=7,
    )
    assert seen["max_calls"] == 7


def test_budget_exceeded_error_from_call_for_judgement_propagates_as_a_hard_stop(monkeypatch, tmp_path, episode_dir):
    # Simulates the real cap firing at its actual enforcement point (inside
    # call_for_judgement()) -- must stop immediately, not be caught by the
    # generic `except Exception` retry/continue clause and treated as just
    # another failed attempt.
    episode_path, storage_dir, payload_root, payload_dir = _real_payload_dir(tmp_path, episode_dir)

    calls = {"judge": 0}

    def _raises_budget_exceeded(pd, model, max_calls=None):
        calls["judge"] += 1
        raise auto_audit.BudgetExceededError("simulated: per-episode LLM call budget exhausted")

    monkeypatch.setattr(auto_audit, "call_for_judgement", _raises_budget_exceeded)

    with pytest.raises(auto_audit.BudgetExceededError):
        auto_audit._run_stage2_call(
            episode_path, "attribute", "asymmetry", "claude-sonnet-5", "test-operator",
            storage_dir, payload_root, dry_run=False, max_attempts=3,
        )
    assert calls["judge"] == 1  # not retried -- one attempt, then the hard stop propagates


def test_no_budget_override_uses_the_shared_default_backward_compatible(monkeypatch, tmp_path, episode_dir):
    # Not passing max_llm_calls explicitly must behave exactly like before
    # this was added -- existing callers are unaffected, using
    # llm.api_client.DEFAULT_MAX_LLM_CALLS_PER_EPISODE.
    episode_path, storage_dir, payload_root, payload_dir = _real_payload_dir(tmp_path, episode_dir)
    monkeypatch.setattr(
        auto_audit, "call_for_judgement",
        lambda pd, model, max_calls=None: {"attribute": "asymmetry", "verdict": "no", "severity": None, "confidence": 0.5, "evidence_pointers": [], "reasoning": "x"},
    )
    monkeypatch.setattr(auto_audit, "ingest_response", lambda *a, **k: {})

    result = auto_audit._run_stage2_call(
        episode_path, "attribute", "asymmetry", "claude-sonnet-5", "test-operator",
        storage_dir, payload_root, dry_run=False, max_attempts=2,
    )
    assert result is True


def test_payload_build_failure_is_not_retried(monkeypatch, tmp_path, episode_dir):
    episode_path, storage_dir, payload_root, payload_dir = _real_payload_dir(tmp_path, episode_dir)

    calls = {"judge": 0}
    monkeypatch.setattr(auto_audit, "call_for_judgement", lambda pd, model, max_calls=None: calls.__setitem__("judge", calls["judge"] + 1))

    result = auto_audit._run_stage2_call(
        episode_path, "attribute", "not_a_real_attribute", "claude-sonnet-5", "test-operator",
        storage_dir, payload_root, dry_run=False, max_attempts=3,
    )

    assert result is False
    assert calls["judge"] == 0  # never even attempted -- the payload itself is invalid, retrying can't fix that


# -- _looks_empty(): the spend guard for a session with nothing worth ------
# -- judging (goal explicitly abandoned, or a single bot-walled step) ------


def test_looks_empty_when_only_one_step():
    episode = {"steps": [{"step_id": 1}], "outcome": {"goal_achieved": None}}
    assert auto_audit._looks_empty(episode) == "only 1 step(s) captured"


def test_looks_empty_when_goal_explicitly_abandoned():
    episode = {"steps": [{"step_id": 1}, {"step_id": 2}, {"step_id": 3}], "outcome": {"goal_achieved": False}}
    assert auto_audit._looks_empty(episode) == "goal was explicitly marked abandoned"


def test_not_empty_with_multiple_steps_and_unmarked_outcome():
    # goal_achieved is None (never clicked either overlay button) -- must
    # NOT be treated the same as an explicit abandon.
    episode = {"steps": [{"step_id": 1}, {"step_id": 2}], "outcome": {"goal_achieved": None}}
    assert auto_audit._looks_empty(episode) is None


def test_not_empty_when_goal_achieved_even_with_few_steps():
    # A short, legitimately successful flow (e.g. a 2-step reject_cookies
    # episode) must not be blocked by a step-count floor alone.
    episode = {"steps": [{"step_id": 1}, {"step_id": 2}], "outcome": {"goal_achieved": True}}
    assert auto_audit._looks_empty(episode) is None


def test_looks_empty_missing_outcome_and_steps_defaults_safely():
    assert auto_audit._looks_empty({}) == "only 0 step(s) captured"


# -- main()'s wiring of the guard: skipped by default, --force-stage2 -----
# -- overrides it, --dry-run is exempt (see test_dry_run_... above) --------


def test_main_skips_stage2_for_a_one_step_episode_without_force(monkeypatch, tmp_path, episode_dir):
    episode_path, storage_dir = episode_dir  # the fixture's own episode is exactly 1 step
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-never-used")
    monkeypatch.setattr(auto_audit, "load_dotenv", lambda *a, **k: None)

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("call_for_judgement must not be called when the episode looks empty")

    monkeypatch.setattr(auto_audit, "call_for_judgement", _fail_if_called)

    payload_root = str(tmp_path / "payload")
    cfg_path = _config_path(tmp_path, storage_dir, payload_root)

    exit_code = auto_audit.main([episode_path, "--config", cfg_path])
    assert exit_code == 0

    # the free stages still ran end to end despite the skip
    episode = load_episode(os.path.join(episode_path, EPISODE_FILENAME))
    assert episode.get("evidence")
    assert (episode.get("mechanism_verdict") or {}).get("computed_output")
    assert os.path.isfile(os.path.join(episode_path, "report.html"))

    # no Stage-2 payload/response was ever written
    episode_id = "episode_auto_audit_test"
    assert not os.path.isfile(os.path.join(payload_root, episode_id, "coordinator", "response.json"))


def test_main_force_stage2_overrides_the_skip(monkeypatch, tmp_path, episode_dir):
    episode_path, storage_dir = episode_dir
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-never-used")
    monkeypatch.setattr(auto_audit, "load_dotenv", lambda *a, **k: None)

    calls = {"judge": 0}

    def _fake_call_for_judgement(pd, model, max_calls=None):
        # payload_dir is .../<episode_id>/attribute/<attribute_name> or
        # .../<episode_id>/coordinator -- see llm/payload_builder.py's
        # build_payload(). Its basename tells us which response shape to
        # fake back.
        calls["judge"] += 1
        leaf = os.path.basename(pd.rstrip("/"))
        if leaf == "coordinator":
            return {"pattern_combinations": []}
        return {
            "attribute": leaf, "verdict": "no", "severity": None, "confidence": 0.5,
            "evidence_pointers": [], "reasoning": "x",
        }

    monkeypatch.setattr(auto_audit, "call_for_judgement", _fake_call_for_judgement)

    payload_root = str(tmp_path / "payload")
    cfg_path = _config_path(tmp_path, storage_dir, payload_root)

    exit_code = auto_audit.main([episode_path, "--force-stage2", "--config", cfg_path])
    assert exit_code == 0
    assert calls["judge"] == len(auto_audit.ATTRIBUTES) + 1  # every attribute + the coordinator
