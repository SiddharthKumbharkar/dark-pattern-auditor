import type { FindingStatus } from "@/lib/types";

const FILL: Record<FindingStatus, string> = {
  confirmed: "bg-brand-red",
  likely: "bg-brand-amber",
  suspicious: "bg-brand-yellow",
  not_detected: "bg-brand-teal",
};

export function ConfidenceGauge({
  confidence,
  status,
}: {
  confidence: number;
  status: FindingStatus;
}) {
  const percent = Math.round(confidence * 100);

  return (
    <div className="flex items-center gap-3">
      <div className="h-2 w-32 overflow-hidden rounded-full bg-brand-surface-raised sm:w-40">
        <div
          className={`h-full rounded-full ${FILL[status]}`}
          style={{ width: `${percent}%` }}
        />
      </div>
      <span className="w-11 text-sm font-semibold tabular-nums text-brand-text">{percent}%</span>
    </div>
  );
}
