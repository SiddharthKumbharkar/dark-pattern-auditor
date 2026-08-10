"""Calls the Anthropic Messages API to produce a Stage-2 LLM judgement from
an already-built payload (llm/payload_builder.py's build_payload() output on
disk) -- the ONLY module in this codebase that makes a live network call to
an LLM (see CLAUDE.md's Layer 4 rule: llm/ is the only layer allowed to).

Deliberately does NOT duplicate any grounding/evidence-pointer validation --
the caller (auto_audit.py) writes this module's return value to response.json
in the same payload directory and runs it through
journey/mechanism_verdict_ingest.py's ingest_response(), the exact function a
human-pasted response goes through. A bad API response is rejected the same
way a bad human paste would be; this module's only job is turning a payload
directory into the same shape a human would have typed in.

Forces the reply through Anthropic's tool-use mechanism (a single synthetic
tool whose input_schema IS response_schema.json) rather than asking for
freeform JSON in prose and parsing it -- more reliable, and produces the
exact same parsed dict shape either way.

Every call is gated by a hard, per-episode call budget (see
BudgetExceededError / _spend_episode_call_budget) enforced HERE, inside
call_for_judgement() itself, before any network request is made -- not one
level up in an orchestrator. auto_audit.py's Stage-2 loop and a one-off
manual/direct call_for_judgement() call (a validation script, a hand-rolled
retry loop) both go through this exact same gate; neither can bypass it.
The count is a JSON file at the episode level, not an in-memory counter, so
it persists across separate process invocations for the same episode --
the gap this closes is specifically an uncapped retry loop spread across
multiple script runs, which an in-memory-only counter would silently miss.
"""

import base64
import io
import json
import mimetypes
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

from PIL import Image

DEFAULT_MODEL = "claude-sonnet-5"
_TOOL_NAME = "submit_judgement"
USAGE_LOG_FILENAME = "usage.json"
BUDGET_LOG_FILENAME = "llm_call_budget.json"

# 7 attributes + coordinator = 8 logical calls per full auto_audit.py run;
# --max-attempts retries each. This is a hard circuit breaker independent
# of that loop shape -- so ANY path to the LLM (orchestrated or direct, one
# run or several against the same episode) can't silently run up the bill.
# Not meant to bind under normal operation (8 * default --max-attempts=2 =
# 16 < 20); it exists for the case where something calls more than that.
DEFAULT_MAX_LLM_CALLS_PER_EPISODE = 20


class BudgetExceededError(RuntimeError):
    """The per-episode LLM call budget was exhausted -- distinct from
    ApiCallError (a single call itself failed). Raised by
    call_for_judgement() BEFORE the network call is made, so the call that
    would exceed the budget never happens and is never counted as an
    attempt. Means the caller should stop making calls for this episode
    entirely, independent of why any individual call succeeded or failed."""

# Published per-million-token USD pricing, used ONLY to log an approximate
# cost alongside the real token counts every call already returns -- never
# read back by anything that affects an ingested judgement. Deliberately a
# small, explicit table (not a live pricing lookup); update if it drifts
# from published rates. Sonnet 5's intro price ($2/$10 through 2026-08-31)
# is intentionally NOT used here -- this logs the standing $3/$15 rate so a
# cost estimate doesn't silently go stale the day the intro period ends.
_PRICE_PER_MTOK_USD = {
    "claude-sonnet-5": {"input": 3.00, "output": 15.00},
    "claude-opus-4-8": {"input": 5.00, "output": 25.00},
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
}

# Anthropic's hard per-image limit is 8000px on the longer edge; full-page
# screenshots of long pages (a category/listing page, say) can genuinely
# exceed that and get the whole request rejected with a 400. Downscaling
# only when a real page actually crosses this line (not proactively, e.g.
# to the ~1568px "optimal" token-cost tier) keeps as much resolution as
# possible for the fine visual detail this task cares about -- contrast,
# legibility, disguise -- while still guaranteeing the request never fails
# on image size.
_MAX_LONG_EDGE_PX = 7900


class ApiCallError(RuntimeError):
    """The API call itself failed, or the model didn't return the forced
    tool call -- distinct from IngestError (journey/mechanism_verdict_ingest.py),
    which rejects an otherwise-successful response's *content*."""


def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _downscaled_png_bytes(path: str) -> bytes:
    with Image.open(path) as img:
        scale = _MAX_LONG_EDGE_PX / max(img.width, img.height)
        new_size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
        resized = img.resize(new_size, Image.LANCZOS)
        buf = io.BytesIO()
        resized.save(buf, format="PNG")
        return buf.getvalue()


def _image_block(path: str) -> Dict:
    with Image.open(path) as img:
        oversized = max(img.width, img.height) > _MAX_LONG_EDGE_PX

    if oversized:
        raw_bytes = _downscaled_png_bytes(path)
        media_type = "image/png"
    else:
        media_type = mimetypes.guess_type(path)[0] or "image/png"
        with open(path, "rb") as f:
            raw_bytes = f.read()

    data = base64.standard_b64encode(raw_bytes).decode("ascii")
    return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}}


def response_schema_to_tool(response_schema: Dict) -> Dict:
    """response_schema.json IS already a JSON Schema object
    ({type, additionalProperties, required, properties[, $defs]}) -- Anthropic's
    tool input_schema takes exactly that shape. Strips the top-level
    $schema/title/description keys (not part of input_schema itself) and
    folds title/description into the tool's own description instead."""
    input_schema = {k: v for k, v in response_schema.items() if k not in ("$schema", "title", "description")}
    description = response_schema.get("description") or response_schema.get("title") or "Submit your judgement."
    return {"name": _TOOL_NAME, "description": description, "input_schema": input_schema}


def build_messages(payload_dir: str) -> List[Dict]:
    """Assembles the exact same content payload/.../INSTRUCTIONS.txt tells a
    human to paste in -- prompt.txt, then evidence_summary.json, then every
    screenshot -- into one user message. No separate system message:
    prompt.txt already contains the full role/task framing (see
    llm/payload_builder.py's prompt templates)."""
    prompt_text = _read_text(os.path.join(payload_dir, "prompt.txt"))
    evidence_summary = _read_text(os.path.join(payload_dir, "evidence_summary.json"))

    content: List[Dict] = [
        {"type": "text", "text": prompt_text},
        {"type": "text", "text": "evidence_summary.json:\n" + evidence_summary},
    ]

    screenshots_dir = os.path.join(payload_dir, "screenshots")
    if os.path.isdir(screenshots_dir):
        for filename in sorted(os.listdir(screenshots_dir)):
            content.append({"type": "text", "text": f"Screenshot: {filename}"})
            content.append(_image_block(os.path.join(screenshots_dir, filename)))

    return [{"role": "user", "content": content}]


def _usage_summary(model: str, usage: object) -> Dict:
    """Real, billed token counts from the API response's own `usage` field
    -- distinct from llm/payload_builder.py's token_estimate, which is a
    PRE-call estimate for --dry-run. `estimated_cost_usd` is None for a
    model not in _PRICE_PER_MTOK_USD (never invented)."""
    input_tokens = getattr(usage, "input_tokens", 0) or 0
    output_tokens = getattr(usage, "output_tokens", 0) or 0
    cache_creation = getattr(usage, "cache_creation_input_tokens", 0) or 0
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0

    prices = _PRICE_PER_MTOK_USD.get(model)
    estimated_cost_usd = None
    if prices:
        # cache_read ~0.1x input, cache_creation ~1.25x input (5-minute TTL
        # default) -- see the claude-api skill's prompt-caching economics.
        cost = (
            input_tokens * prices["input"]
            + cache_read * prices["input"] * 0.1
            + cache_creation * prices["input"] * 1.25
            + output_tokens * prices["output"]
        ) / 1_000_000
        estimated_cost_usd = round(cost, 6)

    return {
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_creation_input_tokens": cache_creation,
        "cache_read_input_tokens": cache_read,
        "estimated_cost_usd": estimated_cost_usd,
    }


def _episode_level_dir(payload_dir: str, role: str) -> str:
    """The inverse of journey/mechanism_verdict_ingest.py's _payload_dir():
    payload_dir is payload_root/episode_id/attribute/<name> for
    role="attribute", payload_root/episode_id/<role> otherwise -- so
    walking up one extra level for "attribute" lands on
    payload_root/episode_id in both cases. That directory is never
    shutil.rmtree()'d by build_payload() (which only removes its own
    role/attribute subdirectory), so a budget file placed there survives
    rebuilding any single attribute's payload -- see
    _spend_episode_call_budget()."""
    if role == "attribute":
        return os.path.dirname(os.path.dirname(payload_dir))
    return os.path.dirname(payload_dir)


def _spend_episode_call_budget(payload_dir: str, max_calls: int) -> None:
    """The one enforcement point for the per-episode LLM call cap -- see
    this module's docstring. Reads/writes a small JSON file at the episode
    level (BUDGET_LOG_FILENAME), keyed by nothing but its own location
    (one file per episode directory), so the count is shared across every
    attribute/role payload for that episode and survives across separate
    process invocations -- a fresh script run against the same episode
    does NOT get a fresh budget.

    Raises BudgetExceededError before incrementing if the episode is
    already at max_calls: the call that would exceed the budget never
    happens, so it is never counted as an attempt either.
    """
    manifest = json.loads(_read_text(os.path.join(payload_dir, "manifest.json")))
    role = manifest["role"]
    episode_id = manifest["episode_id"]
    episode_dir = _episode_level_dir(payload_dir, role)
    os.makedirs(episode_dir, exist_ok=True)
    budget_path = os.path.join(episode_dir, BUDGET_LOG_FILENAME)

    if os.path.isfile(budget_path):
        with open(budget_path, "r", encoding="utf-8") as f:
            budget = json.load(f)
    else:
        budget = {"episode_id": episode_id, "calls_made": 0, "calls": []}

    if budget["calls_made"] >= max_calls:
        raise BudgetExceededError(
            f"Per-episode LLM call budget exhausted ({max_calls} calls already made for "
            f"episode {episode_id!r}) -- refusing to make another. This count persists across "
            f"process invocations (see {budget_path}); pass a higher max_calls to "
            f"call_for_judgement() if this episode genuinely needs more."
        )

    budget["calls_made"] += 1
    budget["calls"].append({
        "at": datetime.now(timezone.utc).isoformat(),
        "role": role,
        "attribute": manifest.get("attribute"),
    })
    with open(budget_path, "w", encoding="utf-8") as f:
        json.dump(budget, f, indent=2)


def call_for_judgement(
    payload_dir: str,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 4096,
    client: Optional[object] = None,
    max_calls: int = DEFAULT_MAX_LLM_CALLS_PER_EPISODE,
) -> Dict:
    """Reads a build-payload output directory, makes ONE API call, and
    returns the parsed judgement dict -- unvalidated against grounding
    rules (see module docstring). `client` is injectable so callers/tests
    can supply their own anthropic.Anthropic() instance; defaults to
    reading ANTHROPIC_API_KEY from the environment via the SDK's own
    lookup.

    Before anything else -- before even the lazy `anthropic` import --
    _spend_episode_call_budget() checks and increments this episode's
    persistent call count, raising BudgetExceededError instead of ever
    reaching the network if `max_calls` is already spent. This is the one
    gate every caller passes through, orchestrated (auto_audit.py) or
    direct (a one-off validation script); see module docstring.

    Also writes payload_dir/usage.json with the real, billed token counts
    (and an approximate USD cost) from this call's own `usage` field, and
    prints a one-line summary -- the return value's shape is unchanged so
    every existing caller (auto_audit.py, a manual script) keeps working;
    this is purely additive logging, not a new contract."""
    _spend_episode_call_budget(payload_dir, max_calls)

    import anthropic  # imported lazily so importing this module never requires the package/key to exist

    response_schema = json.loads(_read_text(os.path.join(payload_dir, "response_schema.json")))
    tool = response_schema_to_tool(response_schema)
    messages = build_messages(payload_dir)

    client = client or anthropic.Anthropic()
    message = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=messages,
        tools=[tool],
        tool_choice={"type": "tool", "name": _TOOL_NAME},
    )

    usage_summary = _usage_summary(model, getattr(message, "usage", None))
    with open(os.path.join(payload_dir, USAGE_LOG_FILENAME), "w", encoding="utf-8") as f:
        json.dump(usage_summary, f, indent=2)
    cost_note = (
        f" -- ~${usage_summary['estimated_cost_usd']:.4f}" if usage_summary["estimated_cost_usd"] is not None else ""
    )
    print(
        f"  usage: {usage_summary['input_tokens']} in / {usage_summary['output_tokens']} out "
        f"(cache read {usage_summary['cache_read_input_tokens']}, write {usage_summary['cache_creation_input_tokens']})"
        f"{cost_note}"
    )

    tool_uses = [block for block in message.content if getattr(block, "type", None) == "tool_use"]
    if not tool_uses:
        raise ApiCallError(
            f"Model did not return a {_TOOL_NAME!r} tool call for {payload_dir} -- "
            f"stop_reason={getattr(message, 'stop_reason', None)!r}"
        )
    return tool_uses[0].input
