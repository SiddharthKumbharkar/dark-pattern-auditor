"""End-to-end test: record two real, linked episodes (a quick signup and
a deliberately restrictive cancel flow -- the same fixture shape as
tests/test_attribute_runner_e2e.py / tests/test_payload_builder.py), run
the real evidence/group-evidence/attribute/payload-builder pipeline, then
ingest real hand-crafted response.json files and check the real
episode.mechanism_verdict written to disk -- not mocks.
"""

import json
import os

import pytest

from attribute_agents.base import ATTRIBUTES
from config.settings import Config
from journey.attribute_runner import run_attributes
from journey.evidence_extractor import extract_evidence
from journey.group_evidence_extractor import extract_group_evidence
from journey.mechanism_verdict_ingest import IngestError, ingest_response
from journey.schema_migration import load_episode
from llm.payload_builder import build_payload
from recorder.interactive_v2 import InteractiveRecorderV2

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
        site_domain="ingest-demo.local",
        sector="ecommerce",
        goal_id=goal_id,
        goal_description="ingest e2e test",
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
    storage_dir = str(tmp_path / "storage")

    signup_dir = _record(
        storage_dir, "episode_ingest_signup", (site_dir / "signup.html").as_uri(),
        "complete_signup", "episode_ingest_cancel", actions=[],
    )
    cancel_dir = _record(
        storage_dir, "episode_ingest_cancel", (site_dir / "cancel1.html").as_uri(),
        "cancel_subscription", "episode_ingest_signup",
        actions=[lambda page: page.click("#next-link"), lambda page: page.click("#unsub-btn")],
    )

    extract_evidence(signup_dir)
    extract_evidence(cancel_dir)
    extract_group_evidence("ingest-demo.local", "complete_signup", storage_dir)
    extract_group_evidence("ingest-demo.local", "cancel_subscription", storage_dir)
    run_attributes(signup_dir, storage_dir=storage_dir)
    run_attributes(cancel_dir, storage_dir=storage_dir)

    payload_root = str(tmp_path / "payload")
    build_payload(signup_dir, role="attribute", attribute="asymmetry", storage_dir=storage_dir, payload_root=payload_root)
    build_payload(signup_dir, role="attribute", attribute="covertness", storage_dir=storage_dir, payload_root=payload_root)
    build_payload(cancel_dir, role="coordinator", storage_dir=storage_dir, payload_root=payload_root)
    build_payload(cancel_dir, role="triage", storage_dir=storage_dir, payload_root=payload_root)

    return {
        "storage_dir": storage_dir,
        "payload_root": payload_root,
        "signup_dir": signup_dir,
        "cancel_dir": cancel_dir,
    }


def _write(tmp_path, name, obj):
    path = os.path.join(str(tmp_path), name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    return path


VALID_ASYMMETRY_RESPONSE = {
    "attribute": "asymmetry",
    "verdict": "fires",
    "severity": 4,
    "confidence": 0.9,
    # #accept-btn sits under the signup fixture's "Create your account" H1,
    # whose text signals/ui_regions.py's keyword match picks up as ancestor
    # context -- "account" matches account_settings, so that's the region
    # the extractor actually assigns here. This response's ui_region must
    # match that exactly (Issue 2: never invented) for ingest to accept it.
    "evidence_pointers": [{"step_id": 1, "selector": "#accept-btn", "ui_region": "account_settings", "signal": "measured_contrast"}],
    "reasoning": "Accept has a much higher measured contrast ratio than reject; reject's font_size_px is also far smaller.",
}


def test_ingest_writes_mechanism_verdict_with_required_metadata(pipeline, tmp_path):
    response_path = _write(tmp_path, "resp.json", VALID_ASYMMETRY_RESPONSE)
    episode = ingest_response(
        pipeline["signup_dir"], role="attribute", response_file=response_path,
        model_name="claude-opus-4-8", operator="sid",
        storage_dir=pipeline["storage_dir"], payload_root=pipeline["payload_root"],
    )
    entries = episode["mechanism_verdict"]["entries"]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["role"] == "attribute"
    assert entry["attribute"] == "asymmetry"
    assert entry["model_name"] == "claude-opus-4-8"
    assert entry["operator"] == "sid"
    assert entry["prompt_version"] == "attribute_prompt.v1"
    assert entry["ingested_at"]
    assert entry["raw_response"] == VALID_ASYMMETRY_RESPONSE

    # Persisted to disk, not just returned in memory.
    on_disk = load_episode(os.path.join(pipeline["signup_dir"], "episode.json"))
    assert on_disk["mechanism_verdict"]["entries"] == entries


def test_attribute_inferred_from_response_body_when_not_passed_explicitly(pipeline, tmp_path):
    response_path = _write(tmp_path, "resp.json", VALID_ASYMMETRY_RESPONSE)
    episode = ingest_response(
        pipeline["signup_dir"], role="attribute", response_file=response_path,
        model_name="m", operator="sid", attribute=None,
        storage_dir=pipeline["storage_dir"], payload_root=pipeline["payload_root"],
    )
    assert episode["mechanism_verdict"]["entries"][0]["attribute"] == "asymmetry"


def test_explicit_attribute_mismatching_response_body_is_rejected(pipeline, tmp_path):
    response_path = _write(tmp_path, "resp.json", VALID_ASYMMETRY_RESPONSE)
    with pytest.raises(IngestError, match="does not match"):
        ingest_response(
            pipeline["signup_dir"], role="attribute", response_file=response_path,
            model_name="m", operator="sid", attribute="complexity",
            storage_dir=pipeline["storage_dir"], payload_root=pipeline["payload_root"],
        )


def test_reingesting_the_same_role_and_attribute_replaces_not_duplicates(pipeline, tmp_path):
    response_path = _write(tmp_path, "resp.json", VALID_ASYMMETRY_RESPONSE)
    for _ in range(3):
        episode = ingest_response(
            pipeline["signup_dir"], role="attribute", response_file=response_path,
            model_name="m", operator="sid",
            storage_dir=pipeline["storage_dir"], payload_root=pipeline["payload_root"],
        )
    assert len(episode["mechanism_verdict"]["entries"]) == 1


def test_different_attributes_accumulate_independently(pipeline, tmp_path):
    asym_path = _write(tmp_path, "asym.json", VALID_ASYMMETRY_RESPONSE)
    cov_path = _write(tmp_path, "cov.json", {
        "attribute": "covertness", "verdict": "fires", "severity": 3, "confidence": 0.6,
        "evidence_pointers": [{"step_id": 1, "selector": "#reject-btn", "ui_region": "account_settings", "signal": "measured_contrast"}],
        "reasoning": "Reject option is measurably harder to notice than accept.",
    })
    ingest_response(pipeline["signup_dir"], role="attribute", response_file=asym_path,
                     model_name="m", operator="sid", storage_dir=pipeline["storage_dir"], payload_root=pipeline["payload_root"])
    episode = ingest_response(pipeline["signup_dir"], role="attribute", response_file=cov_path,
                               model_name="m", operator="sid", storage_dir=pipeline["storage_dir"], payload_root=pipeline["payload_root"])
    attrs = sorted(e["attribute"] for e in episode["mechanism_verdict"]["entries"])
    assert attrs == ["asymmetry", "covertness"]


def test_coordinator_role_ingests_into_mechanism_verdict_with_null_attribute(pipeline, tmp_path):
    # overall_verdict/top_findings/human_review_recommended/summary are no
    # longer part of the coordinator's response (Issue 1) -- those are
    # computed by build_output.py from episode.attributes.results. The
    # coordinator's job is just pattern_combinations, which may legitimately
    # be empty (no region_groups worth naming as a pattern here).
    response = {"pattern_combinations": []}
    response_path = _write(tmp_path, "coord.json", response)
    episode = ingest_response(
        pipeline["cancel_dir"], role="coordinator", response_file=response_path,
        model_name="m", operator="sid",
        storage_dir=pipeline["storage_dir"], payload_root=pipeline["payload_root"],
    )
    entry = episode["mechanism_verdict"]["entries"][0]
    assert entry["role"] == "coordinator"
    assert entry["attribute"] is None
    assert entry["raw_response"]["pattern_combinations"] == []


def test_triage_role_ingests_into_mechanism_verdict_with_null_attribute(pipeline, tmp_path):
    response = {
        "episode_id": "episode_ingest_cancel",
        "attribute_triage": [
            {"attribute": a, "preliminary_read": "no", "worth_deep_dive": False, "notes": "nothing notable"}
            for a in ATTRIBUTES
        ],
    }
    response_path = _write(tmp_path, "triage.json", response)
    episode = ingest_response(
        pipeline["cancel_dir"], role="triage", response_file=response_path,
        model_name="m", operator="sid",
        storage_dir=pipeline["storage_dir"], payload_root=pipeline["payload_root"],
    )
    entry = episode["mechanism_verdict"]["entries"][0]
    assert entry["role"] == "triage"
    assert entry["attribute"] is None
    assert len(entry["raw_response"]["attribute_triage"]) == len(ATTRIBUTES)


def test_triage_role_rejects_a_short_attribute_triage_list(pipeline, tmp_path):
    # response_schema.json requires exactly len(ATTRIBUTES) entries -- a
    # truncated list (e.g. a model that only addressed some attributes)
    # must be rejected, not silently ingested as partial coverage.
    response = {
        "episode_id": "episode_ingest_cancel",
        "attribute_triage": [
            {"attribute": ATTRIBUTES[0], "preliminary_read": "no", "worth_deep_dive": False, "notes": "x"},
        ],
    }
    response_path = _write(tmp_path, "triage_short.json", response)
    with pytest.raises(IngestError):
        ingest_response(
            pipeline["cancel_dir"], role="triage", response_file=response_path,
            model_name="m", operator="sid",
            storage_dir=pipeline["storage_dir"], payload_root=pipeline["payload_root"],
        )


# -- rejection paths -----------------------------------------------------


def test_schema_violation_is_rejected_with_field_level_errors(pipeline, tmp_path):
    bad = dict(VALID_ASYMMETRY_RESPONSE)
    bad["verdict"] = "definitely_maybe"  # not in the enum
    response_path = _write(tmp_path, "bad.json", bad)
    with pytest.raises(IngestError) as excinfo:
        ingest_response(
            pipeline["signup_dir"], role="attribute", response_file=response_path,
            model_name="m", operator="sid",
            storage_dir=pipeline["storage_dir"], payload_root=pipeline["payload_root"],
        )
    assert any("verdict" in e for e in excinfo.value.errors)
    # nothing written on a rejected ingest
    on_disk = load_episode(os.path.join(pipeline["signup_dir"], "episode.json"))
    assert (on_disk.get("mechanism_verdict") or {}).get("entries", []) == []


def test_fires_with_empty_evidence_pointers_is_rejected_by_schema(pipeline, tmp_path):
    bad = dict(VALID_ASYMMETRY_RESPONSE)
    bad["evidence_pointers"] = []
    response_path = _write(tmp_path, "bad.json", bad)
    # additionalProperties/required checks pass, but the framework's
    # constraints on evidence_pointers only apply downstream (run_agent) --
    # here we're only checking response_schema.json's own constraints. This
    # schema does not forbid empty evidence_pointers on "fires" (that hard
    # rule lives in attribute_agents/base.py, applied to code agents), so
    # this specific case is expected to PASS schema validation --
    # confirming the boundary of what ingest-response does and doesn't
    # enforce on its own.
    episode = ingest_response(
        pipeline["signup_dir"], role="attribute", response_file=response_path,
        model_name="m", operator="sid",
        storage_dir=pipeline["storage_dir"], payload_root=pipeline["payload_root"],
    )
    assert episode["mechanism_verdict"]["entries"][0]["raw_response"]["evidence_pointers"] == []


def test_fabricated_step_id_in_evidence_pointers_is_rejected(pipeline, tmp_path):
    bad = dict(VALID_ASYMMETRY_RESPONSE)
    bad["evidence_pointers"] = [{"step_id": 9999, "selector": "#nope", "ui_region": "account_settings", "signal": "made_up"}]
    response_path = _write(tmp_path, "bad.json", bad)
    with pytest.raises(IngestError, match="does not exist in this episode"):
        ingest_response(
            pipeline["signup_dir"], role="attribute", response_file=response_path,
            model_name="m", operator="sid",
            storage_dir=pipeline["storage_dir"], payload_root=pipeline["payload_root"],
        )


def test_null_step_id_in_evidence_pointers_is_not_treated_as_fabricated(pipeline, tmp_path):
    # null step_id is legitimate for group-level evidence (see
    # EvidencePointer's schema docstring) -- must not be rejected.
    ok = dict(VALID_ASYMMETRY_RESPONSE)
    # a null selector has no element to look a region up for -- must claim
    # "unclassified", not whatever region a nearby real element happens to have.
    ok["evidence_pointers"] = [{"step_id": None, "selector": None, "ui_region": "unclassified", "signal": "friction_metrics.friction_ratio"}]
    response_path = _write(tmp_path, "ok.json", ok)
    episode = ingest_response(
        pipeline["signup_dir"], role="attribute", response_file=response_path,
        model_name="m", operator="sid",
        storage_dir=pipeline["storage_dir"], payload_root=pipeline["payload_root"],
    )
    assert episode["mechanism_verdict"]["entries"][0]["raw_response"]["evidence_pointers"][0]["step_id"] is None


def test_malformed_json_file_is_rejected_cleanly(pipeline, tmp_path):
    response_path = os.path.join(str(tmp_path), "broken.json")
    with open(response_path, "w", encoding="utf-8") as f:
        f.write("{not valid json")
    with pytest.raises(IngestError, match="not valid JSON"):
        ingest_response(
            pipeline["signup_dir"], role="attribute", response_file=response_path,
            model_name="m", operator="sid",
            storage_dir=pipeline["storage_dir"], payload_root=pipeline["payload_root"],
        )


def test_missing_response_file_is_rejected_cleanly(pipeline, tmp_path):
    with pytest.raises(IngestError, match="not found"):
        ingest_response(
            pipeline["signup_dir"], role="attribute", response_file=str(tmp_path / "nope.json"),
            model_name="m", operator="sid",
            storage_dir=pipeline["storage_dir"], payload_root=pipeline["payload_root"],
        )


def test_missing_payload_directory_reports_run_build_payload_first(pipeline, tmp_path):
    response_path = _write(tmp_path, "resp.json", {
        "attribute": "complexity", "verdict": "no", "severity": None, "confidence": 0.5,
        "evidence_pointers": [], "reasoning": "clean",
    })
    with pytest.raises(IngestError, match="build-payload"):
        ingest_response(
            pipeline["signup_dir"], role="attribute", response_file=response_path,
            model_name="m", operator="sid",  # complexity payload was never built for signup
            storage_dir=pipeline["storage_dir"], payload_root=pipeline["payload_root"],
        )


def test_model_name_and_operator_are_required(pipeline, tmp_path):
    response_path = _write(tmp_path, "resp.json", VALID_ASYMMETRY_RESPONSE)
    with pytest.raises(IngestError):
        ingest_response(
            pipeline["signup_dir"], role="attribute", response_file=response_path,
            model_name="", operator="sid",
            storage_dir=pipeline["storage_dir"], payload_root=pipeline["payload_root"],
        )
    with pytest.raises(IngestError):
        ingest_response(
            pipeline["signup_dir"], role="attribute", response_file=response_path,
            model_name="m", operator="",
            storage_dir=pipeline["storage_dir"], payload_root=pipeline["payload_root"],
        )
