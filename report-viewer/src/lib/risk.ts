import type { Finding } from "@/lib/types";

export type RiskLevel = "high" | "medium" | "low";

export interface OverallRisk {
  level: RiskLevel;
  confirmedCount: number;
  likelyCount: number;
  suspiciousCount: number;
  notDetectedCount: number;
  humanReviewCount: number;
  headline: string;
}

export function computeOverallRisk(findings: Finding[]): OverallRisk {
  const confirmed = findings.filter((f) => f.status === "confirmed");
  const likely = findings.filter((f) => f.status === "likely");
  const suspicious = findings.filter((f) => f.status === "suspicious");
  const notDetected = findings.filter((f) => f.status === "not_detected");
  const humanReviewCount = findings.filter((f) => f.recommended_human_review).length;
  const confirmedHigh = confirmed.filter((f) => f.severity === "high").length;

  let level: RiskLevel;
  if (confirmedHigh >= 2 || confirmed.length >= 4) {
    level = "high";
  } else if (confirmed.length >= 1 || likely.length >= 2) {
    level = "medium";
  } else {
    level = "low";
  }

  const parts: string[] = [];
  if (confirmed.length > 0) parts.push(`${confirmed.length} confirmed`);
  if (likely.length > 0) parts.push(`${likely.length} likely`);
  if (suspicious.length > 0) parts.push(`${suspicious.length} suspicious`);
  const summary = parts.length > 0 ? parts.join(", ") : "no violations detected";
  const levelLabel = level === "high" ? "High" : level === "medium" ? "Elevated" : "Low";

  return {
    level,
    confirmedCount: confirmed.length,
    likelyCount: likely.length,
    suspiciousCount: suspicious.length,
    notDetectedCount: notDetected.length,
    humanReviewCount,
    headline: `${summary} — ${levelLabel} overall risk`,
  };
}
