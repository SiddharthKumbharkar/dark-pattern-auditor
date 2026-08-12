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
These four commands are the entire setup — there's nothing else to install
or configure to run this on a different machine.

### API key (only needed for the paid Stage-2 pass)

Recording, evidence extraction, the 7 code-based attribute agents, and every
report are **free, local computation** — no key needed for any of that. A
key is only required for `auto_audit.py` / `dpa.py auto-audit` and
`record --auto-audit`, the commands that actually call the Anthropic API:

```bash
cp .env.example .env
# then edit .env and paste in a real key from https://console.anthropic.com/settings/keys
```

`.env` is already gitignored — your key never gets committed. `python-dotenv`
loads it automatically from the project root; no shell export needed (though
`export ANTHROPIC_API_KEY=sk-ant-...` works too, if you'd rather not use a
file). A missing key is caught up front, before anything runs — you'll never
lose a recording session to a key you forgot to set.

Every command is available two ways:

```bash
python3 dpa.py <command> [args...]     # unified entry point (recommended)
python3 <command_script>.py [args...]  # each command's own script, standalone
```

`dpa.py <command> --help` prints exactly what running that script directly
would — `dpa.py` is a thin dispatcher, not a reimplementation, so both forms
always stay in sync. Run `python3 dpa.py --help` for the full command list.

## Full worked example: auditing any site

Every command below in one continuous, copy-pasteable pass — replace
`https://example-shop.com` with the real target and adjust goals as needed.
This is the same pipeline described in more detail in the sections below;
this is the "just show me all of it" version.

```bash
# 0. See what goals are available (add more in config.yaml's goals: list if
#    the site needs one that isn't there).
python3 dpa.py list-goals

# 1. Record -- a real, visible browser opens; you click through the site
#    yourself. Ctrl+C when done. (Repeat for --revisit-index 1, 2, ... a day
#    or more later if you want claim-persistence/timer-reset checks, and/or
#    for a second, --pair-with'd flow like a cancel page paired with signup.)
python3 dpa.py record --site https://example-shop.com \
    --goal purchase_cheapest --operator "your-name"
#   -> prints the new episode_id, e.g. episode_20260729T120000000000Z

# 2. Measure evidence from what was captured -- pure code, no LLM.
python3 dpa.py extract-evidence episode_20260729T120000000000Z

# 3. If you recorded more than one episode of the same (site_id, goal)
#    (revisits, or a --pair-with'd counterpart), join them:
python3 dpa.py extract-group-evidence example-shop.com purchase_cheapest

# 4. Run the 7 code-based attribute agents.
python3 dpa.py run-attributes episode_20260729T120000000000Z

# 5. Compute the final output document -- overall verdict + region-grouped
#    findings, derived from the verdicts above. Nothing here judges
#    anything new; it only assembles what's already there.
python3 dpa.py build-output episode_20260729T120000000000Z

# 6. Sanity checks (optional but recommended before trusting the result):
python3 dpa.py verify-masking episode_20260729T120000000000Z
python3 dpa.py validate-episode storage/episode_20260729T120000000000Z/episode.json

# 7. Build the human-readable HTML report -- findings first (one card per
#    region with a fired attribute), then coverage, then the full verdicts
#    table, then the screenshot filmstrip and evidence tables.
python3 dpa.py report episode_20260729T120000000000Z
#   -> open storage/episode_20260729T120000000000Z/report.html in a browser

# 8. (optional, Stage 2) For attributes code can't judge alone --
#    covertness, information_hiding, disparate_treatment always, or any
#    attribute you want a second opinion on -- hand it to an LLM by hand:
python3 dpa.py build-payload episode_20260729T120000000000Z \
    --role attribute --attribute covertness
#   -> paste payload/episode_.../attribute/covertness/{prompt.txt,
#      evidence_summary.json, screenshots/} into your LLM, save its reply
#      as response.json in that same folder, then:
python3 dpa.py ingest-response episode_20260729T120000000000Z \
    --role attribute --file response.json --model "claude-opus-4-8" --operator "your-name"
python3 dpa.py compare-verdicts episode_20260729T120000000000Z
#   -> re-run build-output (step 5) and report (step 7) so the ingested LLM
#      verdict is folded into the final document -- build-output always
#      prefers a manually-ingested Stage-2 verdict over the code agent's own.
python3 dpa.py build-output episode_20260729T120000000000Z
python3 dpa.py report episode_20260729T120000000000Z

# 9. If you recorded more than one goal/revisit for this site, roll them
#    all up into one page:
python3 dpa.py report-site example-shop.com
```

Every stage is idempotent (safe to re-run any time, e.g. after recording a
new revisit) and every command supports `--config <path>` to point at a
different `config.yaml`, and (via `dpa.py --log-file <path> --log-level
<level> <command> ...`) structured JSON logging of the whole run.

## One-command automated audit (spends money)

Steps 2, 4, 5, 7 above — plus a real Stage-2 LLM pass on all 7 attributes
and the coordinator — collapsed into one command, once you've recorded a
session. Requires `ANTHROPIC_API_KEY` (see **API key** above); this is the
**only** command in this whole tool that spends real money.

```bash
python3 dpa.py auto-audit episode_20260729T120000000000Z
#   -> extract-evidence -> run-attributes -> Stage-2 LLM pass (7 attributes
#      + coordinator, real API calls) -> build-output -> report
#   -> prints the final verdict and where report.html landed

# See exactly what would be sent (token/image counts per call) and what it
# would cost, without spending anything:
python3 dpa.py auto-audit episode_20260729T120000000000Z --dry-run
```

Or trigger it automatically the moment a recording session ends:

```bash
python3 dpa.py record --site https://example-shop.com \
    --goal purchase_cheapest --auto-audit
```

Every Stage-2 response is validated by the exact same grounding/evidence-
pointer/visual-claim checks the manual `ingest-response` workflow uses (see
below) — a rejected or ungrounded response is retried, then skipped (never
silently forced through), same as the manual path. Two built-in safety
nets, both overridable:

- **A hard per-episode call budget** (`--max-llm-calls`, default 20) —
  enforced inside the API-calling function itself, so it applies whether
  you're running the orchestrated pipeline above or scripting direct calls
  of your own; persists across separate process runs against the same
  episode, not just in-memory for one invocation.
- **An empty-episode skip** — if a session looks empty (goal explicitly
  abandoned, or only a single step captured — e.g. a bot-walled landing
  page and nothing else happened), the Stage-2 LLM pass is skipped
  automatically so a dead session doesn't spend money finding out it had
  nothing to judge. `extract-evidence`/`run-attributes`/`build-output`/
  `report` still run either way, free. Override with `--force-stage2`.

Real, per-call cost is logged (`payload/<episode_id>/.../usage.json`) —
actual billed token counts and an estimated USD figure, not a guess.

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
| `--profile <name>` | Launch with a persistent browser profile (under `browser_profiles.root`, gitignored) instead of a fresh throwaway one — cookies/localStorage/site permissions from an earlier session recorded with the *same* profile name carry over. Useful for a bot-check/CAPTCHA you already cleared by hand, or a real logged-in session you want to reuse. Omit for the default one-off, cookie-less context. |
| `--auto-audit` / `--model` | See **One-command automated audit** above — runs the full paid Stage-2 pipeline the moment the session ends. |

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

# 5. Assemble the final output document -- overall.verdict, region-grouped
#    findings (regions), and the flat verdicts list, all derived from the
#    verdicts written in step 4 (and any Stage-2 entries already ingested,
#    see below). Pure presentation: never changes a verdict, only groups
#    and summarizes what's already there. Idempotent -- re-run any time.
python3 dpa.py build-output <episode_id>

# 6. (optional) Verify nothing unmasked slipped through, and validate the
#    episode against the schema
python3 dpa.py verify-masking <episode_id>
python3 dpa.py validate-episode <episode_id>/episode.json

# 7. Build a single-episode HTML report -- findings (region cards) and
#    coverage first, then the full verdicts table, then the screenshot
#    filmstrip with every evidence pointer drawn on the page as a
#    bounding box
python3 dpa.py report <episode_id>
# ...or roll up every goal/revisit for one site into one page:
python3 dpa.py report-site <site_id>
```

### Presentation-ready report views

`report`'s default output (`report.html`, above) is the technical report —
raw evidence tables, selectors, every verdict's reasoning. For a non-
technical audience (a live demo, a manager), two additional views read the
exact same underlying data and translate it into plain language — no
selectors, no JSON, no attribute codes outside a parenthetical next to
their own plain-English label:

```bash
# One episode: a verdict banner, named findings in plain prose, and a
# flagged screenshot filmstrip -- writes report_summary.html alongside
# report.html (never touches report.html itself; run plain `report
# <episode_id>` first/separately if that doesn't exist yet).
python3 dpa.py report <episode_id> --summary

# Two episodes side by side -- the ON/OFF demo artifact: same site, same
# flow, opposite results. Column labels are auto-derived from each
# episode's own site/id (e.g. this project's own "-on"/"-off" demo-site
# convention), never a raw path. Writes report_compare.html.
python3 dpa.py report --compare <on_episode_id> <off_episode_id>
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

Then re-run `build-output <episode_id>` (and `report <episode_id>` if you
want the HTML updated too) — it always prefers a manually-ingested Stage-2
verdict over the code agent's own for that attribute, so the ingested
answer now flows into `overall`/`regions` without anything else changing.

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

## Where everything is stored

Two config-controlled roots, nothing else:

| Root | Config key | Default | Holds |
|---|---|---|---|
| Episode storage | `output.root` | `storage/` | Every recorded episode, cross-episode group evidence, site rollups, demo-suite progress. |
| LLM payloads | `payload.root` | `payload/` | Everything `build-payload` writes for a manual LLM handoff. |

Both are plain directories, resolved relative to the project root unless
given as an absolute path (`config.yaml`, or `--config <path>` per
command). Neither is committed to git (see `.gitignore`) — they're your
local run data, not source.

Exact layout:

```
storage/                                       # output.root
  <episode_id>/
    episode.json                                # the full v2 record: steps, evidence, attributes, mechanism_verdict
    episode_meta.json                            # lightweight summary (goal, operator, step count) -- what list-episodes reads
    steps.jsonl                                  # incremental per-step log, written during recording (crash recovery -- see `recover`)
    run_manifest.json                             # git hash, config snapshot, tool version, operator for this run
    screenshots/  dom/  computed_styles/          # masked artifacts only -- raw/unmasked never lands here
    report.html                                   # written by `report` / `report-site` (technical)
    report_summary.html                           # written by `report --summary` (plain-language)
    report_compare.html                           # written by `report --compare` (side-by-side ON/OFF; lands in the FIRST episode's own folder)
  groups/<group_id>/
    group_evidence.json                           # claim_persistence, timer_reset_detection, paired_flow_comparison for one (site_id, goal)
  site_reports/
    <site_id>.html                                # written by `report-site`
  demo_suite_progress.json                        # resumable session tracking for `run-demo-suite` (Auralis harness only)

payload/                                       # payload.root
  <episode_id>/
    triage/                                       # --role triage
    coordinator/                                  # --role coordinator
    attribute/<attribute_name>/                   # --role attribute --attribute <name>
      prompt.txt  evidence_summary.json  screenshots/  response_schema.json  manifest.json  INSTRUCTIONS.txt

baselines.json                                 # project root -- calibrated median/p25/p75 thresholds; recomputed by `update-baselines`
logs/dpa.jsonl                                 # default JSON-lines audit log for every dpa.py invocation (--log-file to change)
annotation_export.csv / .json                  # project root by default; `export-for-annotation --out` to change
```

## Tests

```bash
make test          # or: python3 -m pytest -q
make lint           # ruff: syntax errors + unused imports/vars/undefined names
```

Every test in this repo exercises the *real* pipeline — real (headless)
Playwright recordings against local HTML fixtures, fed through the actual
extractors/agents/CLIs — not mocks, per this project's own convention.
