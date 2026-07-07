export const CCPA_CATEGORIES = [
  "False Urgency",
  "Basket Sneaking",
  "Confirm Shaming",
  "Forced Action",
  "Subscription Trap",
  "Interface Interference",
  "Bait & Switch",
  "Drip Pricing",
  "Disguised Advertisements",
  "Nagging",
  "Trick Wording",
  "SaaS Billing",
  "Rogue Malware",
] as const;

export const STATUS_LABEL: Record<string, string> = {
  confirmed: "Confirmed",
  likely: "Likely",
  suspicious: "Suspicious",
  not_detected: "Not Detected",
};

export const SEVERITY_LABEL: Record<string, string> = {
  high: "High",
  medium: "Medium",
  low: "Low",
};

// Descending priority order used for default sort and stat ordering.
export const STATUS_ORDER = ["confirmed", "likely", "suspicious", "not_detected"];
export const SEVERITY_ORDER = ["high", "medium", "low"];
