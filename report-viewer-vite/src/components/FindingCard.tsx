
import { useState } from "react";
import type { Finding } from "@/lib/types";
import { StatusBadge } from "@/components/StatusBadge";
import { SeverityTag } from "@/components/SeverityTag";

export function FindingCard({ finding }: { finding: Finding }) {
  const isRecessed = finding.status === "not_detected";
  const [expanded, setExpanded] = useState(!isRecessed);

  return (
    <div
      className={`rounded-2xl border p-6 transition-colors ${
        isRecessed
          ? "border-brand-border/60 bg-brand-surface/40"
          : "border-brand-border bg-brand-surface"
      }`}
    >
      <div className="flex flex-wrap items-center gap-3">
        <h3 className={`text-lg font-semibold ${isRecessed ? "text-brand-muted" : "text-brand-text"}`}>
          {finding.pattern}
        </h3>
        <StatusBadge status={finding.status} />
        <SeverityTag severity={finding.severity} />
        {finding.recommended_human_review && (
          <span className="inline-flex items-center gap-1.5 rounded-full border border-brand-amber/40 bg-brand-amber/10 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-brand-amber">
            <svg viewBox="0 0 20 20" className="h-3 w-3" fill="currentColor" aria-hidden="true">
              <path d="M10 2 1 18h18L10 2Zm0 5a1 1 0 0 1 1 1v4a1 1 0 1 1-2 0V8a1 1 0 0 1 1-1Zm0 8.2a1.1 1.1 0 1 1 0-2.2 1.1 1.1 0 0 1 0 2.2Z" />
            </svg>
            Human review recommended
          </span>
        )}
      </div>

      {isRecessed && !expanded ? (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="mt-3 text-sm text-brand-muted underline hover:text-brand-text"
        >
          Show reasoning
        </button>
      ) : (
        <div className="mt-5 space-y-4">
          {finding.evidence.length > 0 && (
            <div>
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-brand-muted">
                Evidence
              </p>
              <div className="rounded-lg border border-brand-border bg-brand-bg/60 p-4">
                <ul className="space-y-2">
                  {finding.evidence.map((line, index) => (
                    <li
                      key={index}
                      className="flex gap-2 font-mono text-[13px] leading-relaxed text-brand-muted"
                    >
                      <span className="select-none text-brand-teal">›</span>
                      <span className="min-w-0 flex-1 whitespace-pre-wrap break-words">{line}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}

          <div>
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-brand-muted">
              Reasoning
            </p>
            <blockquote className="rounded-lg border-l-4 border-brand-border bg-brand-surface-raised px-4 py-3 text-[15px] leading-relaxed text-brand-text/90">
              {finding.reasoning}
            </blockquote>
          </div>

          {isRecessed && (
            <button
              type="button"
              onClick={() => setExpanded(false)}
              className="text-sm text-brand-muted underline hover:text-brand-text"
            >
              Collapse
            </button>
          )}
        </div>
      )}
    </div>
  );
}
