"""journey/report_summary_builder.py + journey/report_summary_html.py + the
report.py --summary/--compare CLI: the presentation-only SUMMARY report
view. Covers the pure-data helpers with plain dict fixtures (fast) and one
real, non-mocked end-to-end pipeline (record -> extract-evidence ->
run-attributes -> build-output -> build_summary_data()/CLI), reusing the
same fixture shape as tests/test_payload_builder.py.
"""

import json
import os

import pytest

import report
from attribute_agents.base import ATTRIBUTES
from config.settings import Config
from journey.attribute_runner import run_attributes
from journey.episode_output_builder import build_episode_output
from journey.evidence_extractor import extract_evidence
from journey.group_evidence_extractor import extract_group_evidence
from journey.report_summary_builder import (
    ATTRIBUTE_LABELS,
    _asymmetry_sentence,
    _element_phrase,
    _join_and,
    _severity_label,
    build_summary_data,
    default_compare_label,
)
from journey.schema_migration import load_episode, validate_v2
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
<button id="keep-btn" type="button"
  style="background:#000;color:#fff;font-size:22px;padding:16px;">Keep my membership</button>
<button id="cancel-btn" type="button"
  style="background:#fff;color:#ccc;font-size:9px;padding:2px;">Cancel my membership</button>
<p data-disclosure="cancellation-fee">Cancelling now will incur a fee, charged to your card on file.</p>
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


def _record(storage_dir, episode_id, site_url, goal_id, paired_episode_id, actions, site_domain="summary-demo.local"):
    rec = InteractiveRecorderV2(
        storage_dir=storage_dir,
        episode_id=episode_id,
        site_url=site_url,
        site_domain=site_domain,
        sector="ecommerce",
        goal_id=goal_id,
        goal_description="report summary e2e test",
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
        storage_dir, "episode_summary_signup", (site_dir / "signup.html").as_uri(),
        "complete_signup", "episode_summary_cancel_on", actions=[],
        site_domain="summary-demo.local",
    )
    cancel_on_dir = _record(
        storage_dir, "episode_summary_cancel_on", (site_dir / "cancel1.html").as_uri(),
        "cancel_subscription", "episode_summary_signup",
        actions=[lambda page: page.click("#next-link")],
        site_domain="summary-demo-on.local",
    )
    cancel_off_dir = _record(
        storage_dir, "episode_summary_cancel_off", (site_dir / "cancel1.html").as_uri(),
        "cancel_subscription", "episode_summary_signup",
        actions=[lambda page: page.click("#next-link")],
        site_domain="summary-demo-off.local",
    )

    for episode_dir in (signup_dir, cancel_on_dir, cancel_off_dir):
        extract_evidence(episode_dir)
    extract_group_evidence("summary-demo.local", "complete_signup", storage_dir)
    for episode_dir in (cancel_on_dir, cancel_off_dir):
        run_attributes(episode_dir, storage_dir=storage_dir)

    # build-output so computed_output (banner/regions/coverage) actually
    # exists -- build_summary_data() falls back gracefully without it, but
    # the real CLI path always has it, so the e2e test should too.
    for episode_dir in (cancel_on_dir, cancel_off_dir):
        episode_json = os.path.join(episode_dir, "episode.json")
        episode = load_episode(episode_json)
        computed_output = build_episode_output(episode)
        mechanism_verdict = dict(episode.get("mechanism_verdict") or {})
        mechanism_verdict.setdefault("entries", [])
        mechanism_verdict["computed_output"] = computed_output
        episode["mechanism_verdict"] = mechanism_verdict
        assert not validate_v2(episode)
        with open(episode_json, "w", encoding="utf-8") as f:
            json.dump(episode, f, indent=2)

    return {"storage_dir": storage_dir, "signup_dir": signup_dir, "cancel_on_dir": cancel_on_dir, "cancel_off_dir": cancel_off_dir}


def _all_real_selectors(episode_dir: str) -> set:
    """Every selector this episode's own capture ever produced -- from
    computed_styles (interactive elements) and episode.evidence.ui_regions
    (disclosure elements too) -- the exact set a summary sentence's prose
    must never contain verbatim (see test_no_raw_selector_ever_appears_in_prose)."""
    episode = load_episode(os.path.join(episode_dir, "episode.json"))
    selectors = set()
    for tag in (episode.get("evidence") or {}).get("ui_regions") or []:
        selectors.add(tag["selector"])
    for step in episode.get("steps") or []:
        cs_path = step.get("computed_styles_path")
        if not cs_path:
            continue
        full_path = os.path.join(episode_dir, cs_path)
        if not os.path.isfile(full_path):
            continue
        with open(full_path, "r", encoding="utf-8") as f:
            for element in json.load(f) or []:
                if element.get("selector"):
                    selectors.add(element["selector"])
    return selectors


# -- pure helpers -------------------------------------------------------


def test_attribute_labels_cover_every_real_attribute():
    assert set(ATTRIBUTE_LABELS) == set(ATTRIBUTES)
    for label in ATTRIBUTE_LABELS.values():
        assert label and label[0].isupper()  # every label reads as a proper sentence fragment


def test_severity_label_bands():
    assert _severity_label(None) is None
    assert _severity_label(1) == "low"
    assert _severity_label(2) == "low"
    assert _severity_label(3) == "medium"
    assert _severity_label(4) == "high"
    assert _severity_label(5) == "high"


def test_join_and_grammar():
    assert _join_and([]) == ""
    assert _join_and(["a"]) == "a"
    assert _join_and(["a", "b"]) == "a and b"
    assert _join_and(["a", "b", "c"]) == "a, b and c"


def test_default_compare_label_detects_the_demo_site_on_off_convention():
    assert default_compare_label({"site": "auralis-on.local", "episode_id": "x"}) == "Manipulative version (dark patterns on)"
    assert default_compare_label({"site": "auralis-off.local", "episode_id": "x"}) == "Honest version (dark patterns off)"
    assert default_compare_label({"site": None, "episode_id": "episode_cancel_on_v2"}) == "Manipulative version (dark patterns on)"


def test_default_compare_label_never_returns_a_raw_path_and_does_not_false_positive():
    # "confirmation" contains the letters "on" but not as a separate,
    # boundary-delimited token -- must not be misdetected as the ON demo.
    label = default_compare_label({"site": "confirmation-page.example.com", "episode_id": "episode_x"})
    assert label == "confirmation-page.example.com"
    # Never the raw CLI path a caller might mistakenly pass as `site`.
    assert "/" not in default_compare_label({"site": "example.com", "episode_id": "episode_x"})


def test_element_phrase_quotes_a_real_captured_elements_own_text():
    computed_styles_by_step = {1: [{"selector": "#cancel-btn", "text": "Cancel my membership", "tag": "button", "role": ""}]}
    phrase = _element_phrase(1, "#cancel-btn", "asymmetry", computed_styles_by_step, {})
    assert phrase == 'the "Cancel my membership" button'


def test_element_phrase_never_names_an_unrelated_element_for_information_hiding():
    # The information_hiding special case (see _element_phrase's docstring):
    # a non-disclosure element cited by this attribute is ABSENCE evidence,
    # not the hidden thing itself -- must not be quoted as if it were.
    computed_styles_by_step = {1: [{"selector": "#some-link", "text": "Manage membership", "tag": "a", "role": ""}]}
    phrase = _element_phrase(1, "#some-link", "information_hiding", computed_styles_by_step, {})
    assert phrase is None


def test_element_phrase_quotes_a_real_disclosure_element_for_information_hiding():
    disclosure_by_key = {(6, "p.fee"): "Cancelling now will incur a fee."}
    phrase = _element_phrase(6, "p.fee", "information_hiding", {}, disclosure_by_key)
    assert phrase == 'the disclosure text "Cancelling now will incur a fee."'


def test_asymmetry_sentence_reads_the_pairs_own_measured_ratio():
    pair = {"positive_text": "Keep my membership", "negative_text": "Cancel", "area_ratio": 3.0}
    sentence = _asymmetry_sentence(pair, "Unequal choice prominence")
    assert sentence == 'Unequal choice prominence: "Cancel" is noticeably smaller than "Keep my membership".'

    pair_reversed = {"positive_text": "Keep", "negative_text": "Cancel my membership entirely", "area_ratio": 0.2}
    sentence_reversed = _asymmetry_sentence(pair_reversed, "Unequal choice prominence")
    assert '"Keep" is noticeably smaller' in sentence_reversed


# -- real, non-mocked end-to-end pipeline -------------------------------


def test_build_summary_data_runs_end_to_end_on_a_real_episode(pipeline):
    episode = load_episode(os.path.join(pipeline["cancel_on_dir"], "episode.json"))
    data = build_summary_data(episode, pipeline["cancel_on_dir"])

    assert data["banner"]["level"] in ("clean", "warn", "danger")
    assert data["banner"]["heading"]
    assert data["banner"]["plain_language"]
    assert data["meta"]["site"] == "summary-demo-on.local"
    assert data["meta"]["goal_label"] == "Cancel subscription"
    assert data["meta"]["date"]  # steps have real timestamps
    assert "coverage_sentence" in data and data["coverage_sentence"]

    filmstrip_step_ids = {s["step_id"] for s in episode["steps"]}
    assert {s["step_id"] for s in data["steps"]} == filmstrip_step_ids
    for step in data["steps"]:
        if step["flagged"]:
            assert step["flag_level"] in ("fires", "unsure")
            assert step["sentences"]


def test_no_raw_selector_ever_appears_in_prose(pipeline):
    """The single strongest, most generic invariant the style requirement
    ("no raw selectors ... anywhere in the summary view") can be tested
    against: collect every real selector this episode's capture ever
    produced, and assert NONE of them appear as a literal substring in any
    prose text field -- only ever inside a sentence's own `selectors` list
    (the hover-tooltip channel), never in what's actually displayed."""
    episode_dir = pipeline["cancel_on_dir"]
    episode = load_episode(os.path.join(episode_dir, "episode.json"))
    data = build_summary_data(episode, episode_dir)
    real_selectors = _all_real_selectors(episode_dir)

    prose_fields = [data["banner"]["plain_language"]]
    for finding in data["findings"]:
        prose_fields.append(finding["pattern_name"])
        prose_fields.append(finding["description"])
        prose_fields.extend(finding["mechanisms"])
    for step in data["steps"]:
        for sentence in step["sentences"]:
            prose_fields.append(sentence["text"])
    prose_fields.append(data["coverage_sentence"])

    for selector in real_selectors:
        if not selector:
            continue
        for text in prose_fields:
            assert selector not in text, f"raw selector {selector!r} leaked into prose: {text!r}"


def test_summary_cli_never_writes_or_touches_report_html(pipeline, tmp_path, monkeypatch):
    episode_dir = pipeline["cancel_on_dir"]
    report_html_path = os.path.join(episode_dir, "report.html")
    assert not os.path.isfile(report_html_path)

    exit_code = report.main([episode_dir, "--summary"])
    assert exit_code == 0

    assert os.path.isfile(os.path.join(episode_dir, "report_summary.html"))
    assert not os.path.isfile(report_html_path)  # --summary never builds the technical report


def test_default_cli_is_unaffected_and_never_writes_summary_files(pipeline):
    episode_dir = pipeline["cancel_on_dir"]
    summary_path = os.path.join(episode_dir, "report_summary.html")
    compare_path = os.path.join(episode_dir, "report_compare.html")
    assert not os.path.isfile(summary_path)
    assert not os.path.isfile(compare_path)

    exit_code = report.main([episode_dir])
    assert exit_code == 0

    assert os.path.isfile(os.path.join(episode_dir, "report.html"))
    assert not os.path.isfile(summary_path)
    assert not os.path.isfile(compare_path)


def test_compare_cli_writes_a_side_by_side_report_with_derived_labels(pipeline):
    on_dir = pipeline["cancel_on_dir"]
    off_dir = pipeline["cancel_off_dir"]

    exit_code = report.main(["--compare", on_dir, off_dir])
    assert exit_code == 0

    compare_path = os.path.join(on_dir, "report_compare.html")
    assert os.path.isfile(compare_path)
    html = open(compare_path, encoding="utf-8").read()
    assert "Manipulative version (dark patterns on)" in html
    assert "Honest version (dark patterns off)" in html
    # never the raw directory path either column was invoked with
    assert on_dir not in html
    assert off_dir not in html


def test_bare_invocation_with_no_episode_and_no_compare_fails_cleanly():
    # episode is nargs='?' specifically so --compare can omit it -- but a
    # bare `report` with neither must still fail (not crash) rather than
    # silently doing nothing.
    assert report.main([]) == 1


def test_compare_takes_the_place_of_the_positional_episode_argument(pipeline):
    # No positional `episode` needed at all when --compare supplies both
    # episodes -- this is what lets `report --compare ON OFF` work without
    # also passing a redundant/ambiguous third positional.
    exit_code = report.main(["--compare", pipeline["cancel_on_dir"], pipeline["cancel_off_dir"]])
    assert exit_code == 0
