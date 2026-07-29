# Architecture

This tool is built as a pipeline of small, idempotent stages, each reading
what the previous one wrote from plain files under `storage/`. Nothing calls
an LLM except `llm/payload_builder.py`, and it deliberately never does
either — it writes exactly what an LLM would need to disk for a human to
paste in by hand, and `journey/mechanism_verdict_ingest.py` reads the reply
back in. No stage drives a browser autonomously; recording is always
human-driven (`recorder/interactive_v2.py`).

CLAUDE.md's original design named 4 layers (recorder → journey → signals →
llm). Two packages were added beyond that during development —
`attribute_agents/` and the `journey/report_*` / `journey/ground_truth.py` /
`journey/demo_suite.py` family — because the roadmap grew a phase (code-based
attribute judgement, then reporting, then a known-answer test harness) the
original 4-layer sketch didn't anticipate. `attribute_agents/` is disclosed
here as a deliberate, scoped departure from "do not add more layers": it
sits between Layer 3 (measurement) and Layer 4 (judgement), and everything
else in it (`journey/report_*`, `journey/ground_truth.py`,
`journey/demo_suite.py`) stayed inside the existing `journey/` (Layer 2)
package rather than spawning new top-level ones.

## Layer 1 — `recorder/` (capture)

Playwright-based capture. No judgement, no LLM calls — only observes and
writes artifacts.

| File | Role |
|---|---|
| `interactive_v2.py` | **The** recorder. Human-driven: launches a headed browser, the human clicks around freely, this observes (click/input-commit/submit/navigation/significant-scroll) and captures a step. Never drives — no autonomous navigation. Handles new tabs/popups, survives SPA navigation, writes incrementally so a crashed session can be rebuilt (`recover_incomplete_episode`). |
| `evidence_probe.py` | Captures computed CSS + geometry (bounding boxes, colors, font sizes) for every interactive element on a step — feeds `signals/visual_asymmetry.py` and the HTML report's bounding-box overlays. |
| `network_capture.py` | CDP Network-domain capture (method/url/status/resource_type only, never bodies). |
| `overlay.py` | The on-page overlay UI (goal, step count, mark-achieved/abandon/note/end buttons) injected into the recorded page. |
| `masking/` | The privacy stage between capture and persistence — `dom_masker.py`, `screenshot_masker.py` (black-boxes redacted regions), `network_masker.py`, `patterns.py` (denylist/allowlist), `placeholders.py`, `masker.py` (orchestrates all three + records `redactions_applied`). Raw/unmasked artifacts are never written to the episode folder, only to a temp dir deleted at session end. |
| `browser.py`, `redaction.py`, `exclusion.py`, `dom.py`, `screenshot.py` | The original v1 pipeline's recorder (`audit.py`'s URL-list/interactive-v1 mode) — a fixed-list-of-URLs or basic interactive capture, its own redaction/exclusion, superseded for the mechanism-attribute pipeline by `interactive_v2.py` + `masking/` but still functional and tested. |
| `ocr.py` | **Unimplemented stub (0 bytes).** OCR extraction was never built; `extraction_confidence.ocr_used` exists in the schema but always reads false. |

## Layer 2 — `journey/` (assembly, storage, orchestration)

All file I/O for anything beyond a single Playwright call lives here — this
is the layer that reads/writes episode JSON, computes cross-episode joins,
and runs the code-based judgement stage.

| File | Role |
|---|---|
| `schema_migration.py` | The only place that resolves `schema/*.json`'s cross-file `$ref`s and knows how to migrate a v1 episode into a v2-conformant one (`load_episode`). |
| `manifest.py` | Writes `run_manifest.json` (git hash, config snapshot, tool version, operator) into every episode folder. |
| `privacy.py` | Gate that aborts a run if masking left a leak — `find_privacy_violations`. |
| `baselines.py` | `BaselineStore` — median/p25/p75 thresholds every attribute agent reads instead of a magic number, with goal-scoped overrides. |
| `evidence_extractor.py` | Reads a stored (masked) episode, calls every `signals/*.py` function, writes `episode.evidence`. Idempotent full replace. |
| `group_evidence_extractor.py` | Cross-episode signals needing 2+ episodes of the same `(site_id, goal)`: claim persistence across revisits, timer-reset detection, paired-flow friction comparison. Writes `group_evidence.json`. |
| `attribute_runner.py` | Runs the registered `attribute_agents/*` over a stored episode + its group evidence + baselines, writes `episode.attributes`. |
| `mechanism_verdict_ingest.py` | Validates a manually-pasted LLM `response.json` against the exact schema it was shown, rejects fabricated `evidence_pointers`, writes `episode.mechanism_verdict`. |
| `verdict_reconciliation.py` | Code-agent vs manually-ingested-LLM verdict comparison, per attribute — the primary output of `compare-verdicts`. |
| `annotation_export.py` | Flat `(episode, attribute)` rows for human labelling, reusing the same per-attribute evidence view `llm/payload_builder.py` uses. |
| `ground_truth.py` | Loads/validates `ground_truth.yaml`, computes expected-vs-detected + precision/recall/F1 at the attribute level for one episode — the known-answer test's comparator. |
| `demo_suite.py` | Computes the Auralis demo suite's required recording sessions, tracks a resumable progress file, orchestrates the extraction→attributes→validation pipeline across all of them, builds the consolidated pass/fail report. |
| `report_builder.py` / `report_html.py` / `report_site_builder.py` | Assembles and renders the single-episode and site-rollup HTML reports (screenshot filmstrip, evidence tables, evidence-pointer bounding boxes). |
| `builder.py` / `artifact_store.py` / `schema.py` | The v1 pipeline's journey assembly, artifact path management, and dataclass schema — still used by `audit.py`/`server.py`. |
| `revisit.py` | **Unimplemented stub (0 bytes).** `config.yaml`'s `revisit.offsets_hours` is a real, validated config value, but nothing auto-schedules or reminds an operator to actually revisit — recording a revisit is manual (`--revisit-index N`) today. |

## Layer 3 — `signals/` (pure measurement)

Every function here is pure: no Playwright, no file I/O, no LLM calls, no
subjective judgement — only measurement over already-captured data. This is
the layer `journey/evidence_extractor.py` and `group_evidence_extractor.py`
call into.

**Implemented, feeding `episode.evidence`:** `friction.py` (steps/clicks/
interstitials/dead-ends), `visual_asymmetry.py` (opposing-pair contrast/
area/position from `evidence_probe.py`'s computed styles), `claims.py`
(stock/timer/viewer/deadline claim extraction), `price_drift.py`,
`path_deviation.py` (forced interstitials/redirects/dead-ends),
`complexity.py` (option counts, Flesch-Kincaid reading grade, action
counts), `stated_vs_actual.py` (claimed action vs. actual network
activity), `dom_text.py` (shared text-extraction helper).

**Implemented, feeding `group_evidence.json`:** `claim_persistence.py`,
`timer_reset.py`, `paired_flow.py`.

**v1 pipeline (still used by `audit.py`):** `price.py`, `urgency.py`,
`cart.py`.

**Unimplemented stubs (0 bytes) — the two known, documented pipeline
coverage gaps referenced throughout `ground_truth.yaml`:**
- `popups.py` — no structured popup signal exists yet (occurrence count,
  reappearance timing). Confirm-shaming and nagging-modal patterns are only
  visible today via raw DOM text, not a measured signal.
- `ui_measurements.py` — no general UI-measurement signal beyond what
  `visual_asymmetry.py` already covers.
- `confidence.py`, `forms.py`, `state_diff.py` — also 0 bytes, never built;
  no current consumer depends on them.

## `attribute_agents/` — code-based judgement (Phase 3, extends beyond the original 4 layers)

One agent per mechanism attribute (`asymmetry`, `covertness`, `deception`,
`information_hiding`, `restriction`, `disparate_treatment`, `complexity`),
each implementing `assess(episode, group_evidence, baselines) -> dict`
behind a framework (`base.py`) that enforces the hard rules every agent
must satisfy — not_assessable when a required signal is null,
fires/unsure never ships with empty `evidence_pointers`, every threshold
comes from `baselines.py`, agents are pure functions with no I/O.

- **Real code agents**, each backed by a real `signals/*.py` measurement:
  `asymmetry.py`, `restriction.py`, `deception.py`, `complexity.py`.
- **Explicit Stage-2-only stubs** — always return `not_assessable` with
  reason `"requires LLM judgement — Stage 2"`, never fake a verdict:
  `covertness.py`, `information_hiding.py`, `disparate_treatment.py`. Each
  requires reading intent/context (is a hidden option *deliberately*
  hidden? is a price increase a withheld fee or a user-caused change? is a
  flow difference *unfair* or just inherently different tasks?) that a
  fixed threshold can't judge — that's Stage 2's job (see below).
- `registry.py` — config-driven enable/disable, the single source of truth
  `attribute_runner.py` reads from.

## Layer 4 — `llm/` (the only layer allowed to call an LLM)

- `payload_builder.py` — **the layer's real implementation today.** Builds
  three prompt roles (triage / attribute / coordinator) entirely offline:
  loads a versioned prompt template from `prompts/*.v1.txt` (never inlined
  in code), scopes evidence and screenshots to what that role needs, embeds
  a self-contained `response_schema.json`, and writes everything to disk —
  guaranteed not to call an API (a dedicated test scans its source for any
  network-capable import).
- `judge.py`, `prompt_builder.py`, `output_parser.py` — **unimplemented
  stubs (0 bytes).** These were the original design's "call the API
  directly" path; it was never built. `requirements.txt` still lists
  `anthropic`, but nothing in the codebase imports it outside a test that
  asserts `payload_builder.py` never does.

## Cross-cutting

- `config/settings.py` + `config.yaml` — the single typed configuration
  every entry point resolves paths and behavior from; nothing hardcodes a
  path outside `PROJECT_ROOT`'s own resolution.
- `schema/*.json` — JSON Schema (draft 2020-12) contracts: `episode.v1`,
  `episode.v2` (additive-only extension of v1), `group_evidence.v1`,
  `mechanism_verdict.v1` (standalone, since `episode.v2`'s own
  `mechanism_verdict` field stays freeform so existing episodes never break).
- `ground_truth.yaml` — the Auralis demo site's 8 planted patterns, the
  tool's only known-answer test (see `journey/ground_truth.py`,
  `journey/demo_suite.py`).
- `dpa.py` — unified entry point, a thin dispatcher to every command
  script's own `main(argv)`; `logging_setup.py` — the structured logging
  (JSON to file, human-readable to stdout) every command gets when run
  through it.

## What's deferred to Stage 2

Everything below is a deliberate scope boundary, not an oversight — each
is a real, larger capability the current human-in-the-loop, code-first
pipeline was designed to hand off to cleanly, not to informally half-build:

- **Browser-use / autonomous traversal.** `recorder/interactive_v2.py` is
  built to be strictly passive by design (CLAUDE.md: "the recorder is
  passive, never drives"). There is no agent that navigates a site on its
  own to find flows worth auditing — a human always drives the browser.
- **A live triage agent.** `build-payload --role triage` produces the
  *prompt* for a fast, broad first pass across all 7 attributes, but
  nothing runs it — a human pastes it into an LLM and reads the reply
  themselves. An agent that autonomously triages and decides what deserves
  a deep-dive, without a human in that loop, doesn't exist.
- **Live LLM calls.** `llm/judge.py`, `prompt_builder.py`, and
  `output_parser.py` are empty. `llm/payload_builder.py` is the
  intentional substitute — assemble everything, call nothing — and
  `journey/mechanism_verdict_ingest.py` is the read-back half of that same
  manual loop. Wiring an actual `anthropic` call (present in
  `requirements.txt`, unused everywhere else) is Stage 2 work.
- **Discovery / clustering.** Nothing here discovers new sites or URLs to
  audit, or clusters similar findings/sites/patterns across many audits.
  Every episode is recorded against a URL a human already chose.
- **A memory index.** `baselines.json` is a flat, manually-recomputed table
  of numeric thresholds (`update-baselines`), not a retrieval system.
  There's no embedding store, no similarity search, and no cross-audit
  memory beyond the literal episode JSON files sitting in `storage/` — an
  LLM stage that recalls prior audits' patterns/context doesn't exist.
