import sampleAudit from "../../data/sample-audit.json";
import type { AuditReport } from "@/lib/types";

// Single swap point: to point this dashboard at a live pipeline run instead
// of the static sample, replace the import above (or this function's body)
// with a fetch against your API/file, e.g.:
//
//   export async function getReport(): Promise<AuditReport> {
//     const res = await fetch(process.env.NEXT_PUBLIC_AUDIT_REPORT_URL!, { cache: "no-store" });
//     return res.json();
//   }
//
// Everything downstream (page.tsx and all components) only depends on the
// AuditReport shape, not on where it came from.
export function getReport(): AuditReport {
  return sampleAudit as AuditReport;
}
