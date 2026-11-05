"use client";

import { useMemo, useState } from "react";
import type { AuditReport, FindingStatus, SortKey } from "@/lib/types";
import { computeOverallRisk } from "@/lib/risk";
import { sortFindings } from "@/lib/sort";
import { OverallRiskBanner } from "@/components/OverallRiskBanner";
import { SummaryStats } from "@/components/SummaryStats";
import { FindingsControls } from "@/components/FindingsControls";
import { FindingCard } from "@/components/FindingCard";

export function Dashboard({ report }: { report: AuditReport }) {
  const [statusFilter, setStatusFilter] = useState<FindingStatus | "all">("all");
  const [sortKey, setSortKey] = useState<SortKey>("default");

  const risk = useMemo(() => computeOverallRisk(report.findings), [report.findings]);
  const totalPatternsChecked = report.meta?.total_patterns_checked ?? report.findings.length;

  const { primarySection, recessedSection } = useMemo(() => {
    if (statusFilter !== "all") {
      const filtered = report.findings.filter((f) => f.status === statusFilter);
      return { primarySection: sortFindings(filtered, sortKey), recessedSection: [] as typeof filtered };
    }

    const active = report.findings.filter((f) => f.status !== "not_detected");
    const notDetected = report.findings.filter((f) => f.status === "not_detected");
    return {
      primarySection: sortFindings(active, sortKey),
      recessedSection: sortFindings(notDetected, sortKey),
    };
  }, [report.findings, statusFilter, sortKey]);

  const hasAnyResults = primarySection.length > 0 || recessedSection.length > 0;

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-8 px-6 py-10">
      <OverallRiskBanner risk={risk} />
      <SummaryStats risk={risk} totalPatternsChecked={totalPatternsChecked} />

      <FindingsControls
        statusFilter={statusFilter}
        onStatusFilterChange={setStatusFilter}
        sortKey={sortKey}
        onSortKeyChange={setSortKey}
      />

      {!hasAnyResults && (
        <p className="rounded-xl border border-brand-border bg-brand-surface p-6 text-center text-brand-muted">
          No findings match this filter.
        </p>
      )}

      {primarySection.length > 0 && (
        <div className="flex flex-col gap-4">
          {primarySection.map((finding) => (
            <FindingCard key={finding.pattern} finding={finding} />
          ))}
        </div>
      )}

      {recessedSection.length > 0 && (
        <div className="flex flex-col gap-4">
          <h2 className="text-sm font-semibold uppercase tracking-widest text-brand-muted">
            Checked, not found ({recessedSection.length})
          </h2>
          <div className="flex flex-col gap-3">
            {recessedSection.map((finding) => (
              <FindingCard key={finding.pattern} finding={finding} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
