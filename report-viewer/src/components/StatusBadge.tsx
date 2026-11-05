import type { FindingStatus } from "@/lib/types";
import { STATUS_LABEL } from "@/lib/constants";

const STYLES: Record<FindingStatus, string> = {
  confirmed: "bg-brand-red text-white",
  likely: "bg-brand-amber text-brand-bg",
  suspicious: "border border-brand-yellow text-brand-yellow bg-transparent",
  not_detected: "border border-brand-teal/40 text-brand-teal bg-brand-teal-dim",
};

export function StatusBadge({ status }: { status: FindingStatus }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-wide ${STYLES[status]}`}
    >
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}
