import type { Severity } from "@/lib/types";
import { SEVERITY_LABEL } from "@/lib/constants";

const STYLES: Record<Severity, string> = {
  high: "text-brand-red border-brand-red/40",
  medium: "text-brand-amber border-brand-amber/40",
  low: "text-brand-muted border-brand-border",
};

export function SeverityTag({ severity }: { severity: Severity }) {
  return (
    <span
      className={`inline-flex items-center rounded border px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide ${STYLES[severity]}`}
    >
      {SEVERITY_LABEL[severity] ?? severity} severity
    </span>
  );
}
