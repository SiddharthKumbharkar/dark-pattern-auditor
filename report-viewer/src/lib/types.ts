export type FindingStatus = "confirmed" | "likely" | "suspicious" | "not_detected";
export type Severity = "high" | "medium" | "low";
export type SortKey = "default" | "confidence" | "severity" | "pattern";

export interface Finding {
  pattern: string;
  status: FindingStatus;
  confidence: number; // 0-1
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
