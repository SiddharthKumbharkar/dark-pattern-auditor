# Command Reference

All commands assume your terminal is in the project root:
`cd "/Users/siddharthkumbharkar/Documents/Code/Dark Pattern"`

There are two flavors of both front-end apps:

| Flavor | Directories | Stack | Node requirement |
|---|---|---|---|
| **Next.js** (original) | `demo-site/`, `report-viewer/` | Next.js 16 + Tailwind v4 | Node **≥ 20.9** (hard requirement, will not run on 18.x) |
| **Vite** (Node-18-compatible) | `demo-site-vite/`, `report-viewer-vite/` | Vite 5 + React Router 6 + Tailwind v3 | Node **≥ 18** |

Both flavors are visually and functionally identical — same routes, same dark
patterns, same button text/selectors — so `scripts/audit_demo_site.py` and any
manual click-through work the same against either one. Pick whichever matches
the Node version installed on the machine you're demoing from.

## First-time setup

```bash
# Python pipeline
pip3 install -r requirements.txt
python3 -m playwright install chromium

# demo-site (Next.js, needs Node >=20.9)
cd demo-site && npm install && cd ..

# demo-site-vite (Vite, needs Node >=18)
cd demo-site-vite && npm install && cd ..

# report-viewer (Next.js, needs Node >=20.9)
cd report-viewer && npm install && cd ..

# report-viewer-vite (Vite, needs Node >=18)
cd report-viewer-vite && npm install && cd ..
```

---

## Run the demo site — Next.js (`demo-site/`)

```bash
cd demo-site
npm run dev
```

Open **http://localhost:3000**. The "Dark Patterns: ON/OFF" toggle is in the header.

Production-like (faster, less jank for a live demo):

```bash
cd demo-site
npm run build && npm run start
```

---

## Run the demo site — Vite / Node 18 (`demo-site-vite/`)

```bash
cd demo-site-vite
npm run dev
```

Open **http://localhost:3000**. Same site, same toggle, same routes — just no Next.js.

Use a different port if something else is already on 3000:

```bash
cd demo-site-vite
npm run dev -- --port 3002
```

Production-like:

```bash
cd demo-site-vite
npm run build && npm run preview
```

---

## Run the report viewer — Next.js (`report-viewer/`)

```bash
cd report-viewer
npm run dev -- --port 3001   # use a different port if demo-site is already on 3000
```

Open **http://localhost:3001**. Loads `data/sample-audit.json` by default.

---

## Run the report viewer — Vite / Node 18 (`report-viewer-vite/`)

```bash
cd report-viewer-vite
npm run dev
```

Open **http://localhost:3001** (default port, set in `vite.config.ts`). Loads `data/sample-audit.json` by default.

Production-like:

```bash
cd report-viewer-vite
npm run build && npm run preview
```

---

## Run the auditing tool manually on any website (current pipeline)

The unified entry point is `dpa.py` — every step below is `python3 dpa.py <command> ...`.
Replace `https://example-shop.com` with the real target; each `record` prints
the actual `episode_id` to use in every step after it.

```bash
# 0. See available goals (add more in config.yaml's goals: list if needed)
python3 dpa.py list-goals

# 1. Record -- a real, visible browser opens; you click through the site
#    yourself, Ctrl+C when done
python3 dpa.py record --site https://example-shop.com \
    --goal purchase_cheapest --operator "your-name"
#   -> prints the new episode_id, e.g. episode_20260729T120000000000Z

# 2. Measure evidence from what was captured -- pure code, no LLM
python3 dpa.py extract-evidence episode_20260729T120000000000Z

# 3. Only if you recorded 2+ episodes of the same (site_id, goal)
#    (revisits, or a --pair-with'd counterpart)
python3 dpa.py extract-group-evidence example-shop.com purchase_cheapest

# 4. Run the 7 code-based attribute agents
python3 dpa.py run-attributes episode_20260729T120000000000Z

# 5. Assemble the final output document -- overall verdict + region-grouped
#    findings, derived from step 4's verdicts. Pure presentation, never
#    changes a verdict.
python3 dpa.py build-output episode_20260729T120000000000Z

# 6. Optional sanity checks
python3 dpa.py verify-masking episode_20260729T120000000000Z
python3 dpa.py validate-episode storage/episode_20260729T120000000000Z/episode.json

# 7. Build the HTML report -- findings (region cards) first, then coverage,
#    then the full verdicts table, then the screenshot filmstrip/evidence
python3 dpa.py report episode_20260729T120000000000Z
#   -> open storage/episode_20260729T120000000000Z/report.html

# 8. Optional Stage 2: hand an attribute to an LLM by hand (covertness,
#    information_hiding, disparate_treatment can only ever leave
#    not_assessable this way)
python3 dpa.py build-payload episode_20260729T120000000000Z \
    --role attribute --attribute covertness
#   -> paste prompt.txt + evidence_summary.json + screenshots/ into your LLM,
#      save its reply as response.json in that same payload folder, then:
python3 dpa.py ingest-response episode_20260729T120000000000Z \
    --role attribute --file response.json --model "claude-opus-4-8" --operator "your-name"
python3 dpa.py compare-verdicts episode_20260729T120000000000Z
#   -> re-run 5 and 7 so the ingested LLM verdict is folded in (build-output
#      always prefers a manually-ingested Stage-2 verdict over the code
#      agent's own for that attribute):
python3 dpa.py build-output episode_20260729T120000000000Z
python3 dpa.py report episode_20260729T120000000000Z

# 9. If you recorded more than one goal/revisit for this site, roll them up
python3 dpa.py report-site example-shop.com
```

Every step is idempotent (safe to re-run any time) and takes `--config <path>`
for a non-default `config.yaml`. Every artifact written to
`storage/<episode_id>/` is already privacy-masked before it touches disk.

### Legacy v1 pipeline (`audit.py`)

Superseded by the `dpa.py record` flow above (no privacy masking, no
attribute agents, no region-grouped findings) but still functional — see
`ARCHITECTURE.md` for what it does and doesn't do.

**URL list mode** (visits a fixed list of pages, no clicking):

```bash
python3 audit.py \
  --urls "https://example.com/,https://example.com/product/123" \
  --audit-id my_audit \
  --domain example.com \
  --industry ecommerce \
  --output output_my_audit.json
```

**Interactive mode** (you browse a real site by hand; every navigation and click is captured automatically):

```bash
python3 audit.py \
  --interactive \
  --audit-id real_site_001 \
  --domain example.com \
  --industry ecommerce \
  --output output_real_site_001.json
```

A headed Chromium window opens — browse normally, then press **Ctrl+C** in the terminal to stop and save.

Both modes write screenshots to `storage/screenshots/`, DOM snapshots to `storage/dom/`, and the journey JSON to the `--output` path (or the default).

---

## Auto-run the tool on the demo site

```bash
python3 scripts/audit_demo_site.py
```

One command: starts `demo-site`'s dev server if nothing's running on port 3000 (or reuses it if it's already up), drives a full click-through journey (homepage → product → add to cart → full checkout → free trial signup → account → full cancellation flow), saves the journey JSON to `output_demo_site_full.json`, and stops the server afterward (unless it was already running, in which case it's left alone).

Options:

```bash
python3 scripts/audit_demo_site.py --audit-id my_run             # -> output_my_run.json
python3 scripts/audit_demo_site.py --keep-server                 # don't stop the server afterward
python3 scripts/audit_demo_site.py --port 3005                   # use a different port (only works if nothing else is running for demo-site at all)
python3 scripts/audit_demo_site.py --site-dir demo-site-vite     # audit the Node-18/Vite variant instead of Next.js
```

`--site-dir` auto-detects whether to launch `next dev` or `vite` based on
which one is actually `npm install`-ed in that directory, so the rest of the
click-through journey (routes, button text, exclusion rules) runs identically
either way.

> Next.js only allows one `next dev` per project directory, even across
> different ports — if `demo-site` is already running somewhere, the script
> reuses it automatically as long as it's on port 3000. Vite doesn't have
> this restriction.

---

## Score a pipeline run against ground truth

```bash
python3 benchmark/scorer.py \
  --output output_my_audit.json \
  --ground-truth benchmark/ground_truth/my_audit_truth.json
```

Prints a `Pattern | Ground Truth | Pipeline | Result` table (MATCH / OVER-CALL / UNDER-CALL / STATUS-DIFF) plus a summary.

---

## Run the Python test suite

```bash
python3 -m pytest tests/ -q
```

---

## Quick troubleshooting

- **"Address already in use" / port 3000 busy** — something is already running there. Check with `lsof -ti:3000`; kill with `lsof -ti:3000 | xargs kill` if it's stale.
- **`next dev exited immediately`** — another `next dev` for the same project is already running elsewhere (Next.js 16 blocks a second instance per project directory). Stop it first.
- **Playwright browser missing** — run `python3 -m playwright install chromium`.
