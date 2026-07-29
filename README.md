# Dark Pattern Auditing Tool

A human-in-the-loop, multimodal dark pattern auditing tool. A human auditor
browses a website while the tool records the journey, extracts structured
evidence, runs code-based attribute agents where that's possible, and
assembles offline payloads for a human to hand to an LLM (and ingest the
response back) where it isn't.

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for how every module maps to a
layer, and what's deferred to Stage 2.

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate        # or `make setup`, see below
pip install -r requirements-dev.txt   # requirements.txt + ruff (lint only)
python3 -m playwright install chromium
```

Requires Python 3.10+. No database, no external services — everything reads
and writes plain files under `storage/` (configurable via `config.yaml`).

Every command is available two ways:

```bash
python3 dpa.py <command> [args...]     # unified entry point (recommended)
python3 <command_script>.py [args...]  # each command's own script, standalone
```

`dpa.py <command> --help` prints exactly what running that script directly
would — `dpa.py` is a thin dispatcher, not a reimplementation, so both forms
always stay in sync. Run `python3 dpa.py --help` for the full command list.

## Recording a manual session

Recording is always human-driven: the tool opens a real, visible browser and
you click through the site yourself; it observes and captures every step
automatically. It never drives the browser for you.

```bash
python3 dpa.py list-goals                 # see the configured goal library
python3 dpa.py record --site https://example.com \
    --goal purchase_cheapest
```

The overlay in the browser shows your goal, a running step count, and
buttons to mark the goal achieved, abandon, add a note, or end the session.
Press **Ctrl+C** in the terminal at any point to stop — that's the only way
to end a session, and it's always safe (an interrupted session can be
rebuilt with `recover`, see below).

Useful flags on `record`:

| Flag | Meaning |
|---|---|
| `--revisit-index N` | 0 = first visit. Use 1, 2, ... for later revisits of the same target (needed for claim-persistence and timer-reset checks). |
| `--pair-with <episode_id>` | Link this episode to another (e.g. a cancel-flow episode paired with its signup-flow counterpart) so `restriction`/`disparate_treatment` can compare them. |
| `--device desktop\|mobile` | Viewport preset. |
| `--sector` / `--locale` / `--operator` | Metadata recorded on the episode. |

```bash
python3 dpa.py list-episodes               # everything recorded so far
python3 dpa.py recover <episode_id>        # rebuild episode.json if a session crashed before "End Session"
```

Every artifact written to `storage/<episode_id>/` (screenshots, DOM,
network) is already privacy-masked before it touches disk — raw/unmasked
captures never land in the episode folder, only in a temp dir that's
deleted at session end.

## The full pipeline, in order

Each stage reads what the previous one wrote and is **idempotent** — safe to
re-run any time (e.g. after a code change or a new revisit), it always fully
replaces its own output rather than accumulating stale state.

```bash
# 1. Record (human-driven, see above)
python3 dpa.py record --site <url> --goal <goal_id> [--revisit-index N] [--pair-with <id>]

# 2. Measure evidence from the stored (masked) episode -- pure code, no LLM
python3 dpa.py extract-evidence <episode_id>
python3 dpa.py extract-evidence --all          # re-extract every episode under output.root

# 3. Cross-episode signals -- claim persistence across revisits, timer resets,
#    paired-flow friction comparison. Needs 2+ episodes of the same (site_id, goal).
python3 dpa.py extract-group-evidence <site_id> <goal>

# 4. Run the code-based attribute agents (asymmetry, restriction, deception,
#    complexity are real measurements; covertness/information_hiding/
#    disparate_treatment are explicit Stage-2-only stubs -- see ARCHITECTURE.md)
python3 dpa.py run-attributes <episode_id>

# 5. (optional) Verify nothing unmasked slipped through, and validate the
#    episode against the schema
python3 dpa.py verify-masking <episode_id>
python3 dpa.py validate-episode <episode_id>/episode.json

# 6. Build a single-episode HTML report -- screenshot filmstrip, evidence
#    tables, and every attribute verdict's evidence pointers as clickable
#    links to the screenshot with a bounding box drawn on the element
python3 dpa.py report <episode_id>
# ...or roll up every goal/revisit for one site into one page:
python3 dpa.py report-site <site_id>
```

## Handing a payload to an LLM and ingesting the response (Stage 2, manual)

The tool never calls an LLM API itself. Instead, `build-payload` assembles
*exactly* what a model would need — prompt, compact evidence, masked
screenshots, the exact response schema — and writes it to disk for you to
paste into whatever LLM interface you use by hand. `ingest-response` reads
the reply back in, validating it before it touches the stored episode.

```bash
# Build a payload. Three roles:
python3 dpa.py build-payload <episode_id> --role triage
python3 dpa.py build-payload <episode_id> --role attribute --attribute covertness
python3 dpa.py build-payload <episode_id> --role coordinator
```

This writes `payload/<episode_id>/<role>/[<attribute>/]`:

| File | Purpose |
|---|---|
| `prompt.txt` | Full prompt text, ready to paste as the system/first message. |
| `evidence_summary.json` | Compact evidence relevant to this role — never the raw DOM. |
| `screenshots/` | Only masked screenshots this role needs, attach them all. |
| `response_schema.json` | The exact JSON shape the model's reply must match. |
| `manifest.json` | Metadata, screenshot→step_id mapping, `prompt_version`, a token estimate, and a checksum of every input. |
| `INSTRUCTIONS.txt` | Human-readable "how to use this" — where to save the response, how to ingest it. |

Paste `prompt.txt` + `evidence_summary.json` + the screenshots into your LLM
of choice, ask it to return only the JSON `response_schema.json` describes,
save that reply as `response.json`, then:

```bash
python3 dpa.py ingest-response <episode_id> --role attribute --file response.json \
    --model "claude-opus-4-8" --operator "your-name"
```

This validates the response against the same `response_schema.json` you
were shown, rejects any `evidence_pointers` entry whose `step_id` doesn't
actually exist in the episode (a fabricated pointer), and writes it into
`episode.mechanism_verdict.entries` alongside `model_name`, `prompt_version`,
`ingested_at`, and `operator`. Re-ingesting the same `(role, attribute)`
replaces its prior entry rather than duplicating it.

To see the code agent's verdict next to the manually-ingested LLM verdict
for every attribute — the disagreement set is the point of this comparison,
not a debugging aid:

```bash
python3 dpa.py compare-verdicts <episode_id>
```

To export a flat, one-row-per-`(episode, attribute)` CSV/JSON for human
labelling (empty `human_verdict`/`annotator_id` columns to fill in):

```bash
python3 dpa.py export-for-annotation <episode_id> [<episode_id> ...] [--format csv|json]
```

## Running the Auralis demo suite (the only known-answer test)

The Auralis demo site (`demo-site/`, `demo-site-vite/`) has 8 deliberately
planted dark patterns, toggled on/off by a header button, described in
[`ground_truth.yaml`](ground_truth.yaml). `run-demo-suite` is a guided,
resumable wizard: it tells you exactly which sessions to record (each
reachable goal, patterns on and off, plus the revisit runs some patterns
need), then automatically runs extraction → attributes → validation and
produces one consolidated report.

```bash
# 1. Start the demo site's dev server (in the demo-site/ or demo-site-vite/ directory)
npm run dev            # defaults to :3000

# 2. Run the wizard -- it prints exactly what to record and waits for you
python3 dpa.py run-demo-suite
```

For each pending session it prints the URL to open, whether to toggle
"Dark Patterns" on or off first, a walkthrough of what to do, and the exact
`record.py record` command to run in another terminal. After you record a
session, paste its `episode_id` back in (or type `auto` to let it find your
most recent matching recording, or `skip` to leave it for later — progress
is saved, so you can stop and resume `run-demo-suite` any time).

Once every required session is confirmed, it runs the full pipeline and
prints one report: which planted patterns were detected vs. missed (ON
run), any attribute that fired on a known-clean OFF-mode episode — a **false
positive**, flagged loudly — and the claim-persistence/timer-reset results
from the revisit pair.

**The suite fails (nonzero exit) if the OFF run produces any `"fires"`
verdict.** A missed detection on the ON run lowers recall but does not fail
the suite — several of Auralis's 8 patterns are documented in
`ground_truth.yaml` as currently undetectable by code alone (a
Stage-2-only stub, or a signal that doesn't exist yet) and that's exactly
what this harness is for surfacing.

To check one episode against ground truth directly (mode is auto-detected
from `site_domain`: `auralis-on.local` = patterns on, `auralis-off.local` =
patterns off — a metadata label set via `record --site-domain`, decoupled
from the actual connection URL, not a real hostname):

```bash
python3 dpa.py validate-against-truth <episode_id> --truth ground_truth.yaml
```

## Other commands

Two commands predate (and sit alongside) the mechanism-attribute pipeline
above — both available through `dpa.py` like everything else:

- `dpa.py audit` — the original v1 pipeline: URL-list or basic interactive
  recording, feeding the 13-CCPA-category schema instead of the v2
  evidence/attribute one. See `ARCHITECTURE.md`.
- `dpa.py serve` — runs `server.py`'s FastAPI dashboard backend
  (`--host`/`--port`/`--reload`), for the live-session web dashboard.

## Tests

```bash
make test          # or: python3 -m pytest -q
make lint           # ruff: syntax errors + unused imports/vars/undefined names
```

Every test in this repo exercises the *real* pipeline — real (headless)
Playwright recordings against local HTML fixtures, fed through the actual
extractors/agents/CLIs — not mocks, per this project's own convention.
