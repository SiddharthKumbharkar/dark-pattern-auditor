"""llm/api_client.py -- the payload-directory-to-API-request construction
(build_messages, response_schema_to_tool). Real recorded episode, real
build_payload() output on disk, no mocks -- the actual network call
(call_for_judgement) is deliberately NOT exercised here (see that
function's docstring): it's the one place in this codebase that spends
real money and needs a real API key, verified manually instead.
"""

import base64
import io
import json
import os

import pytest

from config.settings import Config
from journey.attribute_runner import run_attributes
from journey.evidence_extractor import extract_evidence
from llm.api_client import build_messages, response_schema_to_tool
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
        storage_dir=storage_dir, episode_id="episode_api_client_test",
        site_url=(site_dir / "signup.html").as_uri(), site_domain="api-client-test.local",
        sector="ecommerce", goal_id="complete_signup", goal_description="api_client test",
        operator="test-operator", config=Config(),
    )
    rec.launch(headless=True)
    try:
        rec._poll_tick()
    finally:
        rec._teardown_browser()
        rec._cleanup_raw_artifacts()
    rec.finalize()

    extract_evidence(rec.episode_dir)
    run_attributes(rec.episode_dir, storage_dir=storage_dir)
    return rec.episode_dir, storage_dir


def _build(episode_dir, storage_dir, payload_root, role, attribute=None):
    return build_payload(episode_dir, role=role, attribute=attribute, storage_dir=storage_dir, payload_root=payload_root)


# -- build_messages: payload directory with screenshots ---------------------


def test_build_messages_leads_with_prompt_text(tmp_path, episode_dir):
    episode_path, storage_dir = episode_dir
    manifest = _build(episode_path, storage_dir, str(tmp_path / "payload"), "attribute", "asymmetry")
    messages = build_messages(manifest["payload_dir"])

    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    content = messages[0]["content"]
    assert content[0]["type"] == "text"
    prompt_on_disk = open(os.path.join(manifest["payload_dir"], "prompt.txt"), encoding="utf-8").read()
    assert content[0]["text"] == prompt_on_disk


def test_build_messages_includes_evidence_summary_as_text(tmp_path, episode_dir):
    episode_path, storage_dir = episode_dir
    manifest = _build(episode_path, storage_dir, str(tmp_path / "payload"), "attribute", "asymmetry")
    messages = build_messages(manifest["payload_dir"])
    content = messages[0]["content"]

    evidence_on_disk = open(os.path.join(manifest["payload_dir"], "evidence_summary.json"), encoding="utf-8").read()
    assert content[1]["type"] == "text"
    assert evidence_on_disk in content[1]["text"]


def test_build_messages_embeds_every_screenshot_as_a_real_image_block(tmp_path, episode_dir):
    episode_path, storage_dir = episode_dir
    manifest = _build(episode_path, storage_dir, str(tmp_path / "payload"), "attribute", "asymmetry")
    assert manifest["token_estimate"]["screenshot_count"] > 0  # asymmetry has a real accept/reject pair here

    messages = build_messages(manifest["payload_dir"])
    content = messages[0]["content"]
    image_blocks = [c for c in content if c["type"] == "image"]
    assert len(image_blocks) == manifest["token_estimate"]["screenshot_count"]

    screenshots_dir = os.path.join(manifest["payload_dir"], "screenshots")
    on_disk_bytes = {
        name: open(os.path.join(screenshots_dir, name), "rb").read()
        for name in sorted(os.listdir(screenshots_dir))
    }
    decoded = [base64.standard_b64decode(b["source"]["data"]) for b in image_blocks]
    assert sorted(decoded) == sorted(on_disk_bytes.values())
    assert all(b["source"]["type"] == "base64" for b in image_blocks)
    assert all(b["source"]["media_type"] == "image/png" for b in image_blocks)


# -- oversized images: Anthropic hard-rejects anything over 8000px on the long edge --


def test_image_over_the_api_limit_is_downscaled_to_fit(tmp_path):
    from PIL import Image

    from llm.api_client import _MAX_LONG_EDGE_PX, _MAX_TOTAL_IMAGE_BYTES_B64, _image_block_within_budget

    # A real full-page screenshot of a long page can genuinely exceed 8000px
    # tall (seen in practice on a real e-commerce category listing page) --
    # synthesize one at that same aspect ratio rather than depending on
    # Playwright producing a page long enough to trigger it. A generous
    # budget isolates this test to the per-image pixel cap alone -- the
    # combined-total budget has its own tests below.
    oversized_path = tmp_path / "tall_screenshot.png"
    Image.new("RGB", (1440, 9489), color="white").save(oversized_path)

    block, encoded_len = _image_block_within_budget(str(oversized_path), _MAX_TOTAL_IMAGE_BYTES_B64)

    decoded = base64.standard_b64decode(block["source"]["data"])
    assert encoded_len == len(block["source"]["data"])
    with Image.open(io.BytesIO(decoded)) as resized:
        assert max(resized.width, resized.height) <= _MAX_LONG_EDGE_PX
        # aspect ratio preserved within rounding
        assert abs((resized.width / resized.height) - (1440 / 9489)) < 0.001
    assert block["source"]["media_type"] == "image/png"


def test_image_under_the_api_limit_is_sent_unmodified(tmp_path):
    from PIL import Image

    from llm.api_client import _MAX_TOTAL_IMAGE_BYTES_B64, _image_block_within_budget

    normal_path = tmp_path / "normal_screenshot.png"
    Image.new("RGB", (1440, 900), color="white").save(normal_path)
    original_bytes = normal_path.read_bytes()

    block, _ = _image_block_within_budget(str(normal_path), _MAX_TOTAL_IMAGE_BYTES_B64)
    decoded = base64.standard_b64decode(block["source"]["data"])
    assert decoded == original_bytes  # byte-for-byte passthrough, no re-encode


# -- the combined-total budget: separate from the per-image pixel cap above --


def _noisy_png(path, size):
    """A solid-color PNG compresses to near-nothing regardless of
    resolution (PNG's DEFLATE crushes uniform runs), which would make
    encoded size barely track pixel dimensions -- useless for testing
    budget-driven shrinking. Random noise doesn't compress away, so
    encoded size actually scales with resolution the way a real,
    detailed screenshot's does."""
    from PIL import Image

    img = Image.frombytes("RGB", size, os.urandom(size[0] * size[1] * 3))
    img.save(path)


def test_many_screenshots_are_shrunk_to_fit_a_combined_total_budget(tmp_path):
    """The real gap this closes: an 18-screenshot episode where every
    single image is well under the per-image 8000px limit, but the
    COMBINED base64 payload still exceeds the API's total request size and
    gets a 413 -- see llm/api_client.py's _MAX_TOTAL_IMAGE_BYTES_B64
    docstring for the real run that hit this."""
    from PIL import Image

    from llm.api_client import _image_block_within_budget

    path = tmp_path / "screenshot.png"
    _noisy_png(path, (600, 1200))
    unshrunk_len = len(base64.standard_b64encode(path.read_bytes()))

    tight_budget = unshrunk_len // 4
    block, encoded_len = _image_block_within_budget(str(path), tight_budget)

    assert encoded_len < unshrunk_len  # actually shrunk, not passed through
    decoded = base64.standard_b64decode(block["source"]["data"])
    with Image.open(io.BytesIO(decoded)) as shrunk:
        assert max(shrunk.width, shrunk.height) < 1200


def test_shrinking_stops_at_the_minimum_edge_even_if_still_over_budget(tmp_path):
    """A budget so tight nothing could ever fit it must not loop forever or
    shrink an image into illegible mush -- it stops at _MIN_LONG_EDGE_PX
    and sends that, over budget or not (see that constant's docstring)."""
    from PIL import Image

    from llm.api_client import _MIN_LONG_EDGE_PX, _image_block_within_budget

    path = tmp_path / "screenshot.png"
    _noisy_png(path, (600, 1200))

    block, _ = _image_block_within_budget(str(path), byte_budget=1)  # impossible to satisfy

    decoded = base64.standard_b64decode(block["source"]["data"])
    with Image.open(io.BytesIO(decoded)) as shrunk:
        assert max(shrunk.width, shrunk.height) == _MIN_LONG_EDGE_PX


def test_build_messages_labels_each_screenshot_by_filename(tmp_path, episode_dir):
    episode_path, storage_dir = episode_dir
    manifest = _build(episode_path, storage_dir, str(tmp_path / "payload"), "attribute", "asymmetry")
    messages = build_messages(manifest["payload_dir"])
    content = messages[0]["content"]

    screenshots_dir = os.path.join(manifest["payload_dir"], "screenshots")
    filenames = sorted(os.listdir(screenshots_dir))
    label_texts = [c["text"] for c in content if c["type"] == "text" and c["text"].startswith("Screenshot: ")]
    assert label_texts == [f"Screenshot: {name}" for name in filenames]


# -- build_messages: payload directory with zero screenshots -----------------


def test_build_messages_has_no_image_blocks_when_payload_has_no_screenshots(tmp_path, episode_dir):
    episode_path, storage_dir = episode_dir
    manifest = _build(episode_path, storage_dir, str(tmp_path / "payload"), "attribute", "disparate_treatment")
    assert manifest["token_estimate"]["screenshot_count"] == 0  # no group evidence for a single, unpaired episode

    messages = build_messages(manifest["payload_dir"])
    content = messages[0]["content"]
    assert all(c["type"] == "text" for c in content)


# -- usage/cost logging (call_for_judgement, real client injected as a fake) --


class _FakeUsage:
    def __init__(self, input_tokens=100, output_tokens=50, cache_creation_input_tokens=0, cache_read_input_tokens=0):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_creation_input_tokens = cache_creation_input_tokens
        self.cache_read_input_tokens = cache_read_input_tokens


class _FakeToolUseBlock:
    type = "tool_use"

    def __init__(self, input_dict):
        self.input = input_dict


class _FakeMessage:
    def __init__(self, usage, tool_input):
        self.usage = usage
        self.content = [_FakeToolUseBlock(tool_input)]
        self.stop_reason = "tool_use"


class _FakeMessagesResource:
    def __init__(self, message):
        self._message = message
        self.create_call_count = 0

    def create(self, **kwargs):
        self.create_call_count += 1
        return self._message


class _FakeAnthropicClient:
    def __init__(self, message):
        self.messages = _FakeMessagesResource(message)


def test_call_for_judgement_writes_usage_json_with_real_token_counts(tmp_path, episode_dir):
    from llm.api_client import call_for_judgement, USAGE_LOG_FILENAME

    episode_path, storage_dir = episode_dir
    manifest = _build(episode_path, storage_dir, str(tmp_path / "payload"), "attribute", "asymmetry")
    fake_message = _FakeMessage(
        _FakeUsage(input_tokens=1234, output_tokens=56, cache_read_input_tokens=1000),
        {"attribute": "asymmetry", "verdict": "no", "severity": None, "confidence": 0.5, "evidence_pointers": [], "reasoning": "x"},
    )
    fake_client = _FakeAnthropicClient(fake_message)

    result = call_for_judgement(manifest["payload_dir"], model="claude-sonnet-5", client=fake_client)
    assert result["verdict"] == "no"  # unchanged return contract

    usage_path = os.path.join(manifest["payload_dir"], USAGE_LOG_FILENAME)
    assert os.path.isfile(usage_path)
    logged = json.load(open(usage_path, encoding="utf-8"))
    assert logged["model"] == "claude-sonnet-5"
    assert logged["input_tokens"] == 1234
    assert logged["output_tokens"] == 56
    assert logged["cache_read_input_tokens"] == 1000
    assert logged["estimated_cost_usd"] > 0  # sonnet-5 is in the known-price table


def test_call_for_judgement_cost_is_none_for_an_unknown_model(tmp_path, episode_dir):
    from llm.api_client import call_for_judgement, USAGE_LOG_FILENAME

    episode_path, storage_dir = episode_dir
    manifest = _build(episode_path, storage_dir, str(tmp_path / "payload"), "attribute", "asymmetry")
    fake_message = _FakeMessage(
        _FakeUsage(),
        {"attribute": "asymmetry", "verdict": "no", "severity": None, "confidence": 0.5, "evidence_pointers": [], "reasoning": "x"},
    )
    fake_client = _FakeAnthropicClient(fake_message)

    call_for_judgement(manifest["payload_dir"], model="some-future-model-not-in-the-table", client=fake_client)
    logged = json.load(open(os.path.join(manifest["payload_dir"], USAGE_LOG_FILENAME), encoding="utf-8"))
    assert logged["estimated_cost_usd"] is None  # never invented for a model with no known price


def test_usage_summary_pricing_math():
    from llm.api_client import _usage_summary

    summary = _usage_summary("claude-sonnet-5", _FakeUsage(input_tokens=1_000_000, output_tokens=0))
    assert summary["estimated_cost_usd"] == 3.00  # $3/1M input tokens, standing (non-intro) rate


# -- per-episode LLM call budget: enforced INSIDE call_for_judgement() itself
#
# This is the actual fix for the real gap found in production use: earlier
# manual validation calls went straight through call_for_judgement() from a
# one-off script, with no auto_audit.py orchestrator involved at all -- so
# auto_audit.py's OLD budget (a local counter in that module, checked by
# its own caller before invoking call_for_judgement) never saw those calls.
# Moving the check inside call_for_judgement() itself means every path --
# orchestrated or direct, one process or several -- hits the same gate.
# Persisted to a JSON file at the episode level (not an in-memory counter)
# specifically so a FRESH process invocation against the same episode does
# not get a fresh budget -- that's the exact shape of the gap this closes.


def _judgement_dict():
    return {"attribute": "asymmetry", "verdict": "no", "severity": None, "confidence": 0.5, "evidence_pointers": [], "reasoning": "x"}


def test_call_for_judgement_hard_stops_once_the_per_episode_budget_is_exhausted(tmp_path, episode_dir):
    from llm.api_client import BudgetExceededError, call_for_judgement

    episode_path, storage_dir = episode_dir
    manifest = _build(episode_path, storage_dir, str(tmp_path / "payload"), "attribute", "asymmetry")
    fake_client = _FakeAnthropicClient(_FakeMessage(_FakeUsage(), _judgement_dict()))

    # Two calls fit inside a budget of 2.
    call_for_judgement(manifest["payload_dir"], model="claude-sonnet-5", client=fake_client, max_calls=2)
    call_for_judgement(manifest["payload_dir"], model="claude-sonnet-5", client=fake_client, max_calls=2)
    assert fake_client.messages.create_call_count == 2

    # The third call must hard-stop BEFORE reaching the network at all.
    with pytest.raises(BudgetExceededError):
        call_for_judgement(manifest["payload_dir"], model="claude-sonnet-5", client=fake_client, max_calls=2)
    assert fake_client.messages.create_call_count == 2  # unchanged -- never attempted


def test_call_for_judgement_budget_persists_in_a_file_at_the_episode_level(tmp_path, episode_dir):
    from llm.api_client import BUDGET_LOG_FILENAME, call_for_judgement

    episode_path, storage_dir = episode_dir
    manifest = _build(episode_path, storage_dir, str(tmp_path / "payload"), "attribute", "asymmetry")
    fake_client = _FakeAnthropicClient(_FakeMessage(_FakeUsage(), _judgement_dict()))

    call_for_judgement(manifest["payload_dir"], model="claude-sonnet-5", client=fake_client, max_calls=5)
    call_for_judgement(manifest["payload_dir"], model="claude-sonnet-5", client=fake_client, max_calls=5)

    # Episode-level, not inside the attribute's own payload subdirectory --
    # payload/<episode_id>/llm_call_budget.json, a sibling of "attribute/".
    episode_id = "episode_api_client_test"
    budget_path = os.path.join(str(tmp_path / "payload"), episode_id, BUDGET_LOG_FILENAME)
    assert os.path.isfile(budget_path)
    budget = json.load(open(budget_path, encoding="utf-8"))
    assert budget["calls_made"] == 2
    assert len(budget["calls"]) == 2
    assert budget["episode_id"] == episode_id


def test_call_for_judgement_budget_is_shared_across_different_attributes_of_the_same_episode(tmp_path, episode_dir):
    from llm.api_client import BudgetExceededError, call_for_judgement

    episode_path, storage_dir = episode_dir
    payload_root = str(tmp_path / "payload")
    manifest_a = _build(episode_path, storage_dir, payload_root, "attribute", "asymmetry")
    manifest_b = _build(episode_path, storage_dir, payload_root, "attribute", "complexity")
    fake_client = _FakeAnthropicClient(_FakeMessage(_FakeUsage(), _judgement_dict()))

    # One call against each of two DIFFERENT attributes of the SAME episode
    # -- the cap is per-episode, not per-attribute, so this must exhaust a
    # budget of 2 just as surely as two calls against the same attribute.
    call_for_judgement(manifest_a["payload_dir"], model="claude-sonnet-5", client=fake_client, max_calls=2)
    call_for_judgement(manifest_b["payload_dir"], model="claude-sonnet-5", client=fake_client, max_calls=2)

    with pytest.raises(BudgetExceededError):
        call_for_judgement(manifest_a["payload_dir"], model="claude-sonnet-5", client=fake_client, max_calls=2)


def test_call_for_judgement_budget_survives_rebuilding_the_same_attributes_payload(tmp_path, episode_dir):
    # build_payload() shutil.rmtree()s and rewrites its own role/attribute
    # subdirectory on every call -- the budget file must live one level up
    # (at the episode level) so a rebuild of THIS SAME attribute's payload
    # does not silently reset the count back to zero.
    from llm.api_client import BudgetExceededError, call_for_judgement

    episode_path, storage_dir = episode_dir
    payload_root = str(tmp_path / "payload")
    manifest = _build(episode_path, storage_dir, payload_root, "attribute", "asymmetry")
    fake_client = _FakeAnthropicClient(_FakeMessage(_FakeUsage(), _judgement_dict()))

    call_for_judgement(manifest["payload_dir"], model="claude-sonnet-5", client=fake_client, max_calls=1)

    # Rebuild the identical attribute's payload -- a fresh directory tree,
    # same episode.
    rebuilt_manifest = _build(episode_path, storage_dir, payload_root, "attribute", "asymmetry")

    with pytest.raises(BudgetExceededError):
        call_for_judgement(rebuilt_manifest["payload_dir"], model="claude-sonnet-5", client=fake_client, max_calls=1)


def test_call_for_judgement_default_max_calls_matches_the_module_constant(tmp_path, episode_dir):
    # Not passing max_calls explicitly must use DEFAULT_MAX_LLM_CALLS_PER_EPISODE
    # -- the cap applies even when a caller doesn't think about it at all.
    from llm.api_client import DEFAULT_MAX_LLM_CALLS_PER_EPISODE, call_for_judgement

    episode_path, storage_dir = episode_dir
    manifest = _build(episode_path, storage_dir, str(tmp_path / "payload"), "attribute", "asymmetry")
    fake_client = _FakeAnthropicClient(_FakeMessage(_FakeUsage(), _judgement_dict()))

    assert DEFAULT_MAX_LLM_CALLS_PER_EPISODE > 0
    call_for_judgement(manifest["payload_dir"], model="claude-sonnet-5", client=fake_client)  # no max_calls passed
    budget_path = os.path.join(str(tmp_path / "payload"), "episode_api_client_test", "llm_call_budget.json")
    assert json.load(open(budget_path, encoding="utf-8"))["calls_made"] == 1


# -- response_schema_to_tool -------------------------------------------------


def test_response_schema_to_tool_strips_meta_keys_but_keeps_the_json_schema_body(tmp_path, episode_dir):
    import json

    episode_path, storage_dir = episode_dir
    manifest = _build(episode_path, storage_dir, str(tmp_path / "payload"), "attribute", "asymmetry")
    response_schema = json.load(open(os.path.join(manifest["payload_dir"], "response_schema.json"), encoding="utf-8"))

    tool = response_schema_to_tool(response_schema)

    assert tool["name"] == "submit_judgement"
    assert tool["description"]  # non-empty, drawn from the schema's own title/description
    for meta_key in ("$schema", "title", "description"):
        assert meta_key not in tool["input_schema"]
    for real_key in ("type", "required", "properties", "additionalProperties"):
        assert tool["input_schema"][real_key] == response_schema[real_key]


def test_response_schema_to_tool_description_falls_back_to_title_when_no_description():
    schema = {"title": "My Title", "type": "object", "properties": {}}
    tool = response_schema_to_tool(schema)
    assert tool["description"] == "My Title"


def test_response_schema_to_tool_has_a_sane_default_when_neither_title_nor_description():
    schema = {"type": "object", "properties": {}}
    tool = response_schema_to_tool(schema)
    assert tool["description"]
