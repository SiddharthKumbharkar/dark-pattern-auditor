# Dark Pattern Auditor — Report Viewer

A presentation-ready dashboard for displaying dark-pattern audit findings —
built to look like a professional compliance/security report (dark navy,
red for violations, teal for clean) rather than a debug dump of JSON.

## Running it

```bash
cd report-viewer
npm install
npm run dev
```

Open `http://localhost:3000`.

## Sample data

`data/sample-audit.json` is the default data source, loaded via
`src/lib/report.ts::getReport()`. It's a realistic 13-pattern findings set
grounded in the actual journey from `demo-site/` — the same
`audit_id`/`domain` as `output_demo_site_full.json` in the parent project,
citing real `step_id`s and signals (countdown timer, cart items, drip
pricing, etc.) from that run. It was hand-constructed rather than produced
by a real judge run, since `llm/judge.py` in the parent project isn't
implemented yet.

### Swapping in live data

Everything downstream (the page and every component) only depends on the
`AuditReport` shape in `src/lib/types.ts` — nothing else references the
static JSON directly. To point this at a real pipeline run, there's a
single place to change: `src/lib/report.ts`. Replace the body of
`getReport()` with a `fetch` against a file or API endpoint, e.g.:

```ts
export async function getReport(): Promise<AuditReport> {
  const res = await fetch(process.env.NEXT_PUBLIC_AUDIT_REPORT_URL!, { cache: "no-store" });
  return res.json();
}
```

(and make `page.tsx`'s `Home` an `async` function that awaits it).

## Data contract

```ts
interface AuditReport {
  meta?: {              // optional — dashboard degrades gracefully if absent
    audit_id?: string;
    domain?: string;
    audit_date?: string;
    total_patterns_checked?: number;
  };
  findings: Array<{
    pattern: string;
    status: "confirmed" | "likely" | "suspicious" | "not_detected";
    severity: "high" | "medium" | "low";
    evidence: string[];
    reasoning: string;
    recommended_human_review: boolean;
  }>;
}
```

## What's built

- **Overall Risk banner** — one-line synthesized headline (`src/lib/risk.ts`
  computes the level from confirmed/likely counts and confirmed-high-severity
  count).
- **Summary stats row** — patterns checked, confirmed/likely/suspicious/not
  detected counts, human-review count. Confirmed is visually emphasized.
- **Finding cards** — status badge (solid red / amber / yellow outline / muted
  teal outline), severity tag, evidence in a monospace citation-style block,
  reasoning in a quote-style block, and a human-review flag badge.
  `not_detected` cards render collapsed by default (click "Show reasoning" to
  expand) and are grouped into a separate "Checked, not found" section at the
  bottom of the default (unfiltered) view.
- **Filter + sort controls** — filter by status; sort by severity (default,
  with pattern name as tiebreaker), severity only, or pattern name.

No loading spinners anywhere — the report is bundled at build time, so
there's nothing to wait on.
