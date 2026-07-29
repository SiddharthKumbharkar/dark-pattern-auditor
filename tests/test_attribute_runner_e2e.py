"""End-to-end test: record two real, linked episodes (a quick signup and
a deliberately restrictive cancel flow), run the real evidence extractor,
the real group evidence extractor (for restriction/disparate_treatment,
which need a paired episode), and the real attribute runner -- checking
actual computed verdicts against genuine page content, not mocks.
"""


import pytest

from config.settings import Config
from journey.attribute_runner import run_attributes
from journey.evidence_extractor import extract_evidence
from journey.group_evidence_extractor import extract_group_evidence
from journey.schema_migration import validate_v2
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
        site_domain="attr-demo.local",
        sector="ecommerce",
        goal_id=goal_id,
        goal_description="attribute runner e2e test",
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


def test_full_pipeline_evidence_group_evidence_and_attributes(tmp_path, site_dir):
    storage_dir = str(tmp_path / "storage")

    signup_dir = _record(
        storage_dir, "episode_attr_e2e_signup", (site_dir / "signup.html").as_uri(),
        "complete_signup", "episode_attr_e2e_cancel", actions=[],
    )
    cancel_dir = _record(
        storage_dir, "episode_attr_e2e_cancel", (site_dir / "cancel1.html").as_uri(),
        "cancel_subscription", "episode_attr_e2e_signup",
        actions=[lambda page: page.click("#next-link"), lambda page: page.click("#unsub-btn")],
    )

    extract_evidence(signup_dir)
    extract_evidence(cancel_dir)

    # -- group evidence: two calls, one per goal, since site_id is shared
    # but goal differs between the signup and cancel episodes -----------
    extract_group_evidence("attr-demo.local", "complete_signup", storage_dir)
    extract_group_evidence("attr-demo.local", "cancel_subscription", storage_dir)

    signup_episode = run_attributes(signup_dir, storage_dir=storage_dir)
    cancel_episode = run_attributes(cancel_dir, storage_dir=storage_dir)

    assert validate_v2(signup_episode) == []
    assert validate_v2(cancel_episode) == []

    signup_results = {r["attribute"]: r for r in signup_episode["attributes"]["results"]}
    cancel_results = {r["attribute"]: r for r in cancel_episode["attributes"]["results"]}

    # -- asymmetry: signup's ghost "No thanks" button --------------------
    assert signup_results["asymmetry"]["verdict"] == "fires"
    assert signup_results["asymmetry"]["evidence_pointers"]

    # -- complexity: cancel's deliberately dense retention-offer copy ---
    assert cancel_results["complexity"]["verdict"] == "fires"
    assert cancel_results["complexity"]["evidence_pointers"]

    # -- restriction: cancel's own friction_ratio vs its paired signup --
    assert cancel_results["restriction"]["verdict"] in ("fires", "no")  # genuinely computed either way
    assert cancel_results["restriction"]["verdict"] != "not_assessable"  # it WAS paired, so this must resolve

    # -- covertness / information_hiding / disparate_treatment are
    # explicit Stage-2 stubs: always not_assessable with the stub reason,
    # regardless of how strongly the underlying data would have fired
    # under their old (now-removed) heuristics. --------------------------
    for results in (signup_results, cancel_results):
        for attribute in ("covertness", "information_hiding", "disparate_treatment"):
            assert results[attribute]["verdict"] == "not_assessable"
            assert results[attribute]["reasoning"] == "requires LLM judgement — Stage 2"

    # -- every result satisfies the hard rules: fires/unsure always carries
    # non-empty evidence_pointers -----------------------------------------
    for results in (signup_results, cancel_results):
        for result in results.values():
            if result["verdict"] in ("fires", "unsure"):
                assert result["evidence_pointers"], f"{result['attribute']} fired with no evidence"
            if result["verdict"] == "not_assessable":
                assert result["severity"] is None
                assert result["confidence"] == 0.0

    # -- idempotency: re-running produces the same results (modulo extracted_at) --
    rerun = run_attributes(cancel_dir, storage_dir=storage_dir)
    a = dict(cancel_episode["attributes"])
    b = dict(rerun["attributes"])
    a.pop("extracted_at")
    b.pop("extracted_at")
    assert a == b
