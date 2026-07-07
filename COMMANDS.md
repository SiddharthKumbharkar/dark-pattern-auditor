# Command Reference

All commands assume your terminal is in the project root:
`cd "/Users/siddharthkumbharkar/Documents/Code/Dark Pattern"`

## First-time setup

```bash
# Python pipeline
pip3 install -r requirements.txt
python3 -m playwright install chromium

# demo-site
cd demo-site && npm install && cd ..

# report-viewer
cd report-viewer && npm install && cd ..
```

---

## Run the demo site (`demo-site/`)

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

## Run the report viewer (`report-viewer/`)

```bash
cd report-viewer
npm run dev -- --port 3001   # use a different port if demo-site is already on 3000
```

Open **http://localhost:3001**. Loads `data/sample-audit.json` by default.

---

## Run the auditing tool manually on any website

**URL list mode** (visits a fixed list of pages, no clicking):

```bash
python3 audit.py \
  --urls "https://example.com/,https://example.com/product/123" \
  --audit-id my_audit \
  --domain example.com \
  --industry ecommerce \
  --output output_my_audit.json
```

- `--urls` — comma-separated list, visited in order (required unless `--interactive`)
- `--audit-id` — optional; defaults to an auto-generated timestamp
- `--domain` — required
- `--industry` — required (e.g. `ecommerce`, `saas`, `subscription_streaming`)
- `--output` — optional; defaults to `output_{audit-id}.json`

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
python3 scripts/audit_demo_site.py --audit-id my_run     # -> output_my_run.json
python3 scripts/audit_demo_site.py --keep-server         # don't stop the server afterward
python3 scripts/audit_demo_site.py --port 3005           # use a different port (only works if nothing else is running for demo-site at all)
```

> Next.js only allows one `next dev` per project directory, even across
> different ports — if `demo-site` is already running somewhere, the script
> reuses it automatically as long as it's on port 3000.

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
