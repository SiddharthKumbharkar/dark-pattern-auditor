import type { OverallRisk } from "@/lib/risk";

const RISK_STYLES = {
  high: {
    border: "border-brand-red/40",
    bg: "bg-brand-red/10",
    dot: "bg-brand-red",
    label: "High Overall Risk",
    labelColor: "text-brand-red",
  },
  medium: {
    border: "border-brand-amber/40",
    bg: "bg-brand-amber/10",
    dot: "bg-brand-amber",
    label: "Elevated Overall Risk",
    labelColor: "text-brand-amber",
  },
  low: {
    border: "border-brand-teal/40",
    bg: "bg-brand-teal/10",
    dot: "bg-brand-teal",
    label: "Low Overall Risk",
    labelColor: "text-brand-teal",
  },
} as const;

export function OverallRiskBanner({ risk }: { risk: OverallRisk }) {
  const style = RISK_STYLES[risk.level];

  return (
    <div className={`rounded-2xl border ${style.border} ${style.bg} p-6 sm:p-8`}>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-4">
          <span className={`h-3 w-3 flex-shrink-0 rounded-full ${style.dot}`} />
          <div>
            <p className={`text-sm font-semibold uppercase tracking-widest ${style.labelColor}`}>
              {style.label}
            </p>
            <p className="mt-1 text-xl font-semibold text-brand-text sm:text-2xl">
              {risk.confirmedCount} confirmed violation{risk.confirmedCount === 1 ? "" : "s"},{" "}
              {risk.likelyCount} likely
              {risk.suspiciousCount > 0 ? `, ${risk.suspiciousCount} suspicious` : ""}
            </p>
          </div>
        </div>

        {risk.humanReviewCount > 0 && (
          <div className="rounded-lg border border-brand-border bg-brand-surface px-4 py-2 text-sm text-brand-muted">
            <span className="font-semibold text-brand-text">{risk.humanReviewCount}</span>{" "}
            finding{risk.humanReviewCount === 1 ? "" : "s"} flagged for human review
          </div>
        )}
      </div>
    </div>
  );
}
