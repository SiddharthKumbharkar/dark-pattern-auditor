export type FindingStatus = "confirmed" | "likely" | "suspicious" | "not_detected";
export type Severity = "high" | "medium" | "low";
export type SortKey = "default" | "severity" | "pattern";

export interface Finding {
  pattern: string;
  status: FindingStatus;
  severity: Severity;
  evidence: string[];
  reasoning: string;
  recommended_human_review: boolean;
}

export interface AuditReportMeta {
  audit_id?: string;
  domain?: string;
  audit_date?: string;
  total_patterns_checked?: number;
}

export interface AuditReport {
  meta?: AuditReportMeta;
  findings: Finding[];
}
