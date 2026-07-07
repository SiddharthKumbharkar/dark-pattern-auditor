import type { Finding, SortKey } from "@/lib/types";
import { SEVERITY_ORDER } from "@/lib/constants";

export function sortFindings(findings: Finding[], sortKey: SortKey): Finding[] {
  const copy = [...findings];

  switch (sortKey) {
    case "confidence":
      return copy.sort((a, b) => b.confidence - a.confidence);
    case "severity":
      return copy.sort(
        (a, b) => SEVERITY_ORDER.indexOf(a.severity) - SEVERITY_ORDER.indexOf(b.severity)
      );
    case "pattern":
      return copy.sort((a, b) => a.pattern.localeCompare(b.pattern));
    case "default":
    default:
      return copy.sort((a, b) => {
        const severityDiff = SEVERITY_ORDER.indexOf(a.severity) - SEVERITY_ORDER.indexOf(b.severity);
        if (severityDiff !== 0) return severityDiff;
        return b.confidence - a.confidence;
      });
  }
}
