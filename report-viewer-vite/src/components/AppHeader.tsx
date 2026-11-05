import type { AuditReportMeta } from "@/lib/types";

export function AppHeader({ meta }: { meta?: AuditReportMeta }) {
  return (
    <header className="border-b border-brand-border bg-brand-bg">
      <div className="mx-auto flex max-w-6xl flex-col gap-1 px-6 py-6 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-red/15 text-brand-red">
            <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" aria-hidden="true">
              <path
                d="M12 2 3 6v6c0 5 3.8 8.7 9 10 5.2-1.3 9-5 9-10V6l-9-4Z"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinejoin="round"
              />
              <path d="M12 8v5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
              <circle cx="12" cy="16" r="0.9" fill="currentColor" />
            </svg>
          </div>
          <div>
            <p className="text-sm font-semibold uppercase tracking-widest text-brand-muted">
              Dark Pattern Auditor
            </p>
            <h1 className="text-lg font-semibold text-brand-text">Audit Report</h1>
          </div>
        </div>

        <div className="flex flex-col text-sm text-brand-muted sm:text-right">
          {meta?.domain && (
            <span>
              Target: <span className="text-brand-text">{meta.domain}</span>
            </span>
          )}
          {meta?.audit_date && <span>Audited {meta.audit_date}</span>}
        </div>
      </div>
    </header>
  );
}
