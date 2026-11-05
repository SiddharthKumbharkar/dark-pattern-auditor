
import type { FindingStatus, SortKey } from "@/lib/types";

const STATUS_OPTIONS: { value: FindingStatus | "all"; label: string }[] = [
  { value: "all", label: "All" },
  { value: "confirmed", label: "Confirmed" },
  { value: "likely", label: "Likely" },
  { value: "suspicious", label: "Suspicious" },
  { value: "not_detected", label: "Not Detected" },
];

export function FindingsControls({
  statusFilter,
  onStatusFilterChange,
  sortKey,
  onSortKeyChange,
}: {
  statusFilter: FindingStatus | "all";
  onStatusFilterChange: (value: FindingStatus | "all") => void;
  sortKey: SortKey;
  onSortKeyChange: (value: SortKey) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-4">
      <div className="flex flex-wrap gap-2">
        {STATUS_OPTIONS.map((opt) => (
          <button
            key={opt.value}
            type="button"
            onClick={() => onStatusFilterChange(opt.value)}
            className={`rounded-full border px-3 py-1.5 text-sm font-medium transition-colors ${
              statusFilter === opt.value
                ? "border-brand-teal bg-brand-teal/10 text-brand-teal"
                : "border-brand-border text-brand-muted hover:text-brand-text"
            }`}
          >
            {opt.label}
          </button>
        ))}
      </div>

      <label className="ml-auto flex items-center gap-2 text-sm text-brand-muted">
        Sort by
        <select
          value={sortKey}
          onChange={(e) => onSortKeyChange(e.target.value as SortKey)}
          className="rounded-lg border border-brand-border bg-brand-surface px-3 py-1.5 text-sm text-brand-text focus:border-brand-teal focus:outline-none"
        >
          <option value="default">Severity, then pattern name</option>
          <option value="severity">Severity</option>
          <option value="pattern">Pattern name</option>
        </select>
      </label>
    </div>
  );
}
