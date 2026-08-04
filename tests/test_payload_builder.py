"""End-to-end test: record two real, linked episodes (a quick signup and
a deliberately restrictive cancel flow -- the same fixture shape as
tests/test_attribute_runner_e2e.py), run the real evidence/group-evidence/
attribute pipeline, then build real payloads for all 3 roles and check the
actual files written to disk against genuine computed evidence, not mocks.
"""

import json
import os
import subprocess
import sys

import pytest

from attribute_agents.base import ATTRIBUTES
from config.settings import Config
from journey.attribute_runner import run_attributes
from journey.evidence_extractor import extract_evidence
from journey.group_evidence_extractor import extract_group_evidence
from llm.payload_builder import PayloadBuildError, _build_coordinator, build_payload
from recorder.interactive_v2 import InteractiveRecorderV2

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SIGNUP_HTML = """<!DOCTYPE html>
<html><body>
<h1>Create your account</h1>
<button id="accept-btn" type="button"
  style="background:#000;color:#fff;font-size:20px;padding:14px;">Yes, sign me up</button>
<button id="reject-btn" type="button"
  style="background:#f5f5f5;color:#f0f0f0;font-size:8px;padding:2px;">No thanks</button>
</body></html>
"""

CANCEL_STEP1_HTML = """<!DOCTYPE html>
<html><body>
<h1>Manage membership</h1>
<a id="next-link" href="cancel2.html">Continue to cancel</a>
</body></html>
"""

CANCEL_STEP2_HTML = """<!DOCTYPE html>
<html><body>
<h1>Before you go</h1>
<p>Notwithstanding any prior communication, failure to not decline this retention offer
shall not be deemed an unequivocal, irrevocable non-acceptance of continued billing
absent explicit, unambiguous disaffirmance hereof.</p>
<button id="unsub-btn" type="button">Cancel my membership</button>
</body></html>
"""


@pytest.fixture
def site_dir(tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    (site / "signup.html").write_text(SIGNUP_HTML, encoding="utf-8")
    (site / "cancel1.html").write_text(CANCEL_STEP1_HTML, encoding="utf-8")
    (site / "cancel2.html").write_text(CANCEL_STEP2_HTML, encoding="utf-8")
    return site


def _record(storage_dir, episode_id, site_url, goal_id, paired_episode_id, actions):
    rec = InteractiveRecorderV2(
        storage_dir=storage_dir,
        episode_id=episode_id,
        site_url=site_url,
        site_domain="payload-demo.local",
        sector="ecommerce",
        goal_id=goal_id,
        goal_description="payload builder e2e test",
        operator="test-operator",
        config=Config(),
        paired_episode_id=paired_episode_id,
    )
    page = rec.launch(headless=True)
    try:
        rec._poll_tick()
        for act in actions:
            act(page)
            rec._poll_tick()
    finally:
        rec._teardown_browser()
        rec._cleanup_raw_artifacts()
    rec.finalize()
    return rec.episode_dir


@pytest.fixture
def pipeline(tmp_path, site_dir):
    """Records signup+cancel, runs evidence/group-evidence/attributes on
    both -- the full real pipeline build_payload() assumes has already run."""
    storage_dir = str(tmp_path / "storage")

    signup_dir = _record(
        storage_dir, "episode_payload_signup", (site_dir / "signup.html").as_uri(),
        "complete_signup", "episode_payload_cancel", actions=[],
    )
    cancel_dir = _record(
        storage_dir, "episode_payload_cancel", (site_dir / "cancel1.html").as_uri(),
        "cancel_subscription", "episode_payload_signup",
        actions=[lambda page: page.click("#next-link"), lambda page: page.click("#unsub-btn")],
    )

    extract_evidence(signup_dir)
    extract_evidence(cancel_dir)
    extract_group_evidence("payload-demo.local", "complete_signup", storage_dir)
    extract_group_evidence("payload-demo.local", "cancel_subscription", storage_dir)
    run_attributes(signup_dir, storage_dir=storage_dir)
    run_attributes(cancel_dir, storage_dir=storage_dir)

    payload_root = str(tmp_path / "payload")
    return {
        "storage_dir": storage_dir,
        "payload_root": payload_root,
        "signup_dir": signup_dir,
        "cancel_dir": cancel_dir,
    }


# -- argument validation (no recording needed) ----------------------------


def test_role_must_be_one_of_the_three(tmp_path):
    with pytest.raises(PayloadBuildError):
        build_payload(str(tmp_path), role="not_a_real_role")


def test_attribute_role_requires_attribute_argument(tmp_path):
    with pytest.raises(PayloadBuildError, match="attribute"):
        build_payload(str(tmp_path), role="attribute", attribute=None)


def test_attribute_role_rejects_unknown_attribute_name(tmp_path):
    with pytest.raises(PayloadBuildError):
        build_payload(str(tmp_path), role="attribute", attribute="not_a_real_attribute")


def test_non_attribute_role_rejects_an_attribute_argument(tmp_path):
    with pytest.raises(PayloadBuildError, match="only valid with --role attribute"):
        build_payload(str(tmp_path), role="triage", attribute="asymmetry")


# -- preconditions enforced against a real (but not fully processed) episode --


def test_build_payload_requires_evidence_extraction_first(tmp_path, site_dir):
    storage_dir = str(tmp_path / "storage")
    episode_dir = _record(
        storage_dir, "episode_no_evidence_yet", (site_dir / "signup.html").as_uri(),
        "complete_signup", None, actions=[],
    )
    with pytest.raises(PayloadBuildError, match="extract-evidence"):
        build_payload(episode_dir, role="triage", storage_dir=storage_dir, payload_root=str(tmp_path / "payload"))


def test_coordinator_role_requires_attributes_to_have_run(tmp_path, site_dir):
    storage_dir = str(tmp_path / "storage")
    episode_dir = _record(
        storage_dir, "episode_no_attributes_yet", (site_dir / "signup.html").as_uri(),
        "complete_signup", None, actions=[],
    )
    extract_evidence(episode_dir)
    with pytest.raises(PayloadBuildError, match="run-attributes"):
        build_payload(
            episode_dir, role="coordinator", storage_dir=storage_dir, payload_root=str(tmp_path / "payload")
        )


# -- triage role -----------------------------------------------------------


def test_triage_role_full_file_structure_and_content(pipeline):
    manifest = build_payload(
        pipeline["cancel_dir"], role="triage", storage_dir=pipeline["storage_dir"], payload_root=pipeline["payload_root"]
    )
    payload_dir = manifest["payload_dir"]

    for filename in ("prompt.txt", "evidence_summary.json", "response_schema.json", "manifest.json", "INSTRUCTIONS.txt"):
        assert os.path.isfile(os.path.join(payload_dir, filename)), f"missing {filename}"
    assert os.path.isdir(os.path.join(payload_dir, "screenshots"))

    prompt_text = open(os.path.join(payload_dir, "prompt.txt"), encoding="utf-8").read()
    assert "<<" not in prompt_text, "unfilled placeholder leaked into prompt.txt"
    assert "episode_payload_cancel" in prompt_text

    evidence_summary = json.load(open(os.path.join(payload_dir, "evidence_summary.json"), encoding="utf-8"))
    assert evidence_summary["episode_id"] == "episode_payload_cancel"
    assert "evidence" in evidence_summary
    assert "steps" in evidence_summary
    assert evidence_summary["group_evidence"] is not None

    response_schema = json.load(open(os.path.join(payload_dir, "response_schema.json"), encoding="utf-8"))
    assert response_schema["properties"]["attribute_triage"]["minItems"] == len(ATTRIBUTES)

    # Triage is a broad pass -- every step with a masked screenshot is included.
    screenshots = sorted(os.listdir(os.path.join(payload_dir, "screenshots")))
    assert len(screenshots) == 3
    assert len(manifest["screenshot_step_mapping"]) == 3


def test_triage_screenshots_are_byte_identical_to_the_stored_masked_files_never_raw(pipeline):
    manifest = build_payload(
        pipeline["cancel_dir"], role="triage", storage_dir=pipeline["storage_dir"], payload_root=pipeline["payload_root"]
    )
    payload_dir = manifest["payload_dir"]
    for entry in manifest["screenshot_step_mapping"]:
        copied = open(os.path.join(payload_dir, "screenshots", entry["filename"]), "rb").read()
        original = open(
            os.path.join(pipeline["cancel_dir"], "screenshots", entry["filename"]), "rb"
        ).read()
        assert copied == original


# -- attribute role ----------------------------------------------------


def test_attribute_role_scopes_evidence_and_screenshots_to_that_attribute(pipeline):
    manifest = build_payload(
        pipeline["cancel_dir"], role="attribute", attribute="restriction",
        storage_dir=pipeline["storage_dir"], payload_root=pipeline["payload_root"],
    )
    payload_dir = manifest["payload_dir"]
    assert manifest["attribute"] == "restriction"
    assert "attribute/restriction" in payload_dir.replace(os.sep, "/")

    evidence_summary = json.load(open(os.path.join(payload_dir, "evidence_summary.json"), encoding="utf-8"))
    assert set(evidence_summary["relevant_evidence"].keys()) <= {"friction_metrics", "path_deviation"}
    assert "paired_flow_comparison" in evidence_summary["relevant_group_evidence"]
    # Attributes not relevant to restriction must not leak in.
    assert "complexity_metrics" not in evidence_summary["relevant_evidence"]
    assert "visual_asymmetry" not in evidence_summary["relevant_evidence"]

    # code_agent_result is the real, already-computed restriction verdict.
    assert evidence_summary["code_agent_result"]["attribute"] == "restriction"
    assert evidence_summary["code_agent_result"]["agent_type"] == "code"

    # Screenshots are scoped to evidence_pointers' step_ids only -- not
    # every step in the episode (cancel has 3 steps total).
    mapped_step_ids = {e["step_id"] for e in manifest["screenshot_step_mapping"]}
    pointer_step_ids = {p["step_id"] for p in evidence_summary["evidence_pointers"] if p["step_id"] is not None}
    assert mapped_step_ids == pointer_step_ids
    assert mapped_step_ids  # restriction fired in this fixture, so this must be non-empty
    assert mapped_step_ids < {1, 2, 3} or mapped_step_ids == {1, 2, 3}  # always a subset of real steps

    # Every pointer shown to the human/LLM already carries a ui_region --
    # read from the extractor's own tagging, never left for the model to
    # invent (Issue 2).
    assert evidence_summary["evidence_pointers"]
    for pointer in evidence_summary["evidence_pointers"]:
        assert "ui_region" in pointer and pointer["ui_region"]


def test_attribute_response_schema_matches_assess_output_shape(pipeline):
    manifest = build_payload(
        pipeline["signup_dir"], role="attribute", attribute="asymmetry",
        storage_dir=pipeline["storage_dir"], payload_root=pipeline["payload_root"],
    )
    schema = json.load(open(os.path.join(manifest["payload_dir"], "response_schema.json"), encoding="utf-8"))
    assert set(schema["required"]) == {"attribute", "verdict", "severity", "confidence", "evidence_pointers", "reasoning"}
    assert schema["properties"]["attribute"]["const"] == "asymmetry"
    # agent_version/agent_type are NOT asked of the model -- they're
    # mechanical metadata attached afterward (see INSTRUCTIONS.txt).
    assert "agent_version" not in schema["properties"]
    assert "agent_type" not in schema["properties"]
    # visual_claim_unverified is OPTIONAL (Issue 4) -- present as a
    # property but not required, since it only applies when reasoning
    # makes a visual claim.
    assert "visual_claim_unverified" in schema["properties"]
    assert "visual_claim_unverified" not in schema["required"]
    # ui_region is required on every evidence_pointers entry (Issue 2).
    pointer_schema = schema["properties"]["evidence_pointers"]["items"]
    assert "ui_region" in pointer_schema["required"]


def test_stub_attribute_still_surfaces_its_raw_evidence_even_though_code_result_is_empty(pipeline):
    # covertness is an explicit Stage-2 stub (always not_assessable, empty
    # evidence_pointers) -- but its raw input (visual_asymmetry) still
    # exists and should still reach the human/LLM, otherwise the whole
    # point of a manual Stage-2 pass on this attribute is defeated.
    manifest = build_payload(
        pipeline["signup_dir"], role="attribute", attribute="covertness",
        storage_dir=pipeline["storage_dir"], payload_root=pipeline["payload_root"],
    )
    evidence_summary = json.load(
        open(os.path.join(manifest["payload_dir"], "evidence_summary.json"), encoding="utf-8")
    )
    assert evidence_summary["code_agent_result"]["verdict"] == "not_assessable"
    assert evidence_summary["code_agent_result"]["evidence_pointers"] == []
    assert evidence_summary["code_agent_result"]["reasoning"] == "requires LLM judgement — Stage 2"
    assert evidence_summary["relevant_evidence"]["visual_asymmetry"]  # non-empty raw evidence
    assert evidence_summary["evidence_pointers"]  # synthesized from raw evidence, not empty
    assert manifest["screenshot_step_mapping"]  # screenshots derived from those synthesized pointers


def test_prompt_definition_and_code_agent_note_come_from_the_versioned_prompt_files(pipeline):
    manifest = build_payload(
        pipeline["signup_dir"], role="attribute", attribute="complexity",
        storage_dir=pipeline["storage_dir"], payload_root=pipeline["payload_root"],
    )
    prompt_text = open(os.path.join(manifest["payload_dir"], "prompt.txt"), encoding="utf-8").read()
    assert "Attribute under assessment: complexity" in prompt_text
    assert "reading grade" in prompt_text.lower() or "option" in prompt_text.lower()
    assert manifest["prompt_version"] == "attribute_prompt.v1"
    assert manifest["prompt_file"] == os.path.join("prompts", "attribute_prompt.v1.txt")


# -- coordinator role --------------------------------------------------


def test_coordinator_role_synthesizes_all_attribute_results_and_scopes_screenshots(pipeline):
    manifest = build_payload(
        pipeline["cancel_dir"], role="coordinator", storage_dir=pipeline["storage_dir"], payload_root=pipeline["payload_root"]
    )
    payload_dir = manifest["payload_dir"]

    evidence_summary = json.load(open(os.path.join(payload_dir, "evidence_summary.json"), encoding="utf-8"))
    assert len(evidence_summary["attribute_results"]) == len(ATTRIBUTES)
    assert "outcome" in evidence_summary

    response_schema = json.load(open(os.path.join(payload_dir, "response_schema.json"), encoding="utf-8"))
    # overall_verdict/top_findings/human_review_recommended/summary are no
    # longer asked of the coordinator -- they're computed by build_output.py
    # from episode.attributes.results, not authored (Issue 1). The
    # coordinator's own job shrinks to naming pattern combinations already
    # grouped by ui_region for it.
    assert set(response_schema["required"]) == {"pattern_combinations"}
    assert "overall_verdict" not in response_schema["properties"]
    assert "top_findings" not in response_schema["properties"]

    # region_groups/page_level_co_occurrence are code-computed and handed
    # to the coordinator, not something it derives itself.
    assert "region_groups" in evidence_summary
    assert "page_level_co_occurrence" in evidence_summary

    # Screenshots: union of evidence_pointers from fires/unsure attributes only.
    firing_step_ids = set()
    for result in evidence_summary["attribute_results"]:
        if result["verdict"] in ("fires", "unsure"):
            firing_step_ids.update(p["step_id"] for p in result["evidence_pointers"] if p["step_id"] is not None)
    mapped_step_ids = {e["step_id"] for e in manifest["screenshot_step_mapping"]}
    assert mapped_step_ids == firing_step_ids
    assert mapped_step_ids  # this fixture's cancel flow has real firing attributes


def test_coordinator_falls_back_to_first_and_last_step_when_nothing_fires():
    episode = {
        "episode": {"episode_id": "e1"},
        "outcome": {},
        "steps": [{"step_id": 1}, {"step_id": 2}, {"step_id": 3}],
        "attributes": {
            "results": [
                {"attribute": "asymmetry", "verdict": "no", "severity": None, "confidence": 0.7,
                 "evidence_pointers": [], "reasoning": "clean", "agent_version": "x", "agent_type": "code"},
                {"attribute": "complexity", "verdict": "not_assessable", "severity": None, "confidence": 0.0,
                 "evidence_pointers": [], "reasoning": "n/a", "agent_version": "x", "agent_type": "code"},
            ]
        },
    }
    _summary, step_ids = _build_coordinator(episode)
    assert step_ids == [1, 3]


# -- reproducibility / integrity guarantees --------------------------------


def test_rebuilding_the_same_payload_produces_an_identical_checksum(pipeline):
    m1 = build_payload(
        pipeline["signup_dir"], role="attribute", attribute="asymmetry",
        storage_dir=pipeline["storage_dir"], payload_root=pipeline["payload_root"],
    )
    m2 = build_payload(
        pipeline["signup_dir"], role="attribute", attribute="asymmetry",
        storage_dir=pipeline["storage_dir"], payload_root=pipeline["payload_root"],
    )
    assert m1["checksum"]["combined"] == m2["checksum"]["combined"]
    assert set(m1["checksum"]["files"]) == set(m2["checksum"]["files"])


def test_token_estimate_is_present_and_reasonable(pipeline):
    manifest = build_payload(
        pipeline["cancel_dir"], role="triage", storage_dir=pipeline["storage_dir"], payload_root=pipeline["payload_root"]
    )
    te = manifest["token_estimate"]
    assert te["text_chars"] > 0
    assert te["estimated_tokens"] == round(te["text_chars"] / 4)
    assert te["screenshot_count"] == len(manifest["screenshot_step_mapping"])


def test_payload_builder_never_imports_anything_that_could_call_an_api():
    source = open(os.path.join(REPO_ROOT, "llm", "payload_builder.py"), encoding="utf-8").read()
    for forbidden in ("import anthropic", "from anthropic", "import requests", "urlopen", "httpx"):
        assert forbidden not in source, f"payload_builder.py must never call an API (found {forbidden!r})"


# -- CLI smoke test ----------------------------------------------------


def test_cli_builds_a_payload_and_prints_a_summary(pipeline):
    result = subprocess.run(
        [
            sys.executable, os.path.join(REPO_ROOT, "build_payload.py"),
            pipeline["signup_dir"], "--role", "attribute", "--attribute", "asymmetry",
            "--out", pipeline["payload_root"],
        ],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout
    assert "token_estimate" in result.stdout
    assert "checksum" in result.stdout


def test_cli_fails_cleanly_for_attribute_role_without_attribute_flag(pipeline):
    result = subprocess.run(
        [
            sys.executable, os.path.join(REPO_ROOT, "build_payload.py"),
            pipeline["signup_dir"], "--role", "attribute", "--out", pipeline["payload_root"],
        ],
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "FAIL" in result.stdout
