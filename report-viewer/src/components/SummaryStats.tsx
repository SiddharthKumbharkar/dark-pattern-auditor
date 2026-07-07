import type { OverallRisk } from "@/lib/risk";

export function SummaryStats({
  risk,
  totalPatternsChecked,
}: {
  risk: OverallRisk;
  totalPatternsChecked: number;
}) {
  const stats = [
    { label: "Patterns Checked", value: totalPatternsChecked, tone: "text-brand-text" },
    { label: "Confirmed", value: risk.confirmedCount, tone: "text-brand-red", emphasize: true },
    { label: "Likely", value: risk.likelyCount, tone: "text-brand-amber" },
    { label: "Suspicious", value: risk.suspiciousCount, tone: "text-brand-yellow" },
    { label: "Not Detected", value: risk.notDetectedCount, tone: "text-brand-teal" },
    { label: "Flagged for Review", value: risk.humanReviewCount, tone: "text-brand-text" },
  ];

  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
      {stats.map((stat) => (
        <div
          key={stat.label}
          className={`rounded-xl border p-4 ${
            stat.emphasize
              ? "border-brand-red/30 bg-brand-red/5"
              : "border-brand-border bg-brand-surface"
          }`}
        >
          <p className={`text-3xl font-bold tabular-nums ${stat.tone}`}>{stat.value}</p>
          <p className="mt-1 text-xs font-medium uppercase tracking-wide text-brand-muted">
            {stat.label}
          </p>
        </div>
      ))}
    </div>
  );
}
