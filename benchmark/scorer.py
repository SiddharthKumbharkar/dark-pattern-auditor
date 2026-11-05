"""Compares a pipeline's findings JSON against a ground truth JSON and
prints a per-pattern results table.

No dependencies beyond json and argparse.
"""

import argparse
import json

PATTERNS = [
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
]

POSITIVE_STATUSES = {"confirmed", "likely"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score pipeline findings against ground truth")
    parser.add_argument("--output", required=True, help="Path to pipeline/LLM findings JSON")
    parser.add_argument("--ground-truth", required=True, help="Path to ground truth JSON")
    return parser.parse_args()


def load_status_by_pattern(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    findings = data.get("findings", [])
    return {f.get("pattern"): f.get("status", "not_detected") for f in findings}


def classify(pipeline_status: str, ground_truth_status: str) -> str:
    if pipeline_status == ground_truth_status:
        return "MATCH"
    if ground_truth_status == "not_detected" and pipeline_status in POSITIVE_STATUSES:
        return "OVER-CALL"
    if pipeline_status == "not_detected" and ground_truth_status in POSITIVE_STATUSES:
        return "UNDER-CALL"
    return "STATUS-DIFF"


def score(pipeline_by_pattern: dict, ground_truth_by_pattern: dict) -> list:
    rows = []
    for pattern in PATTERNS:
        pipeline_status = pipeline_by_pattern.get(pattern, "not_detected")
        ground_truth_status = ground_truth_by_pattern.get(pattern, "not_detected")
        result = classify(pipeline_status, ground_truth_status)
        rows.append((pattern, ground_truth_status, pipeline_status, result))
    return rows


def print_table(rows: list) -> None:
    headers = ("Pattern", "Ground Truth", "Pipeline", "Result")
    widths = [
        max(len(headers[i]), max(len(row[i]) for row in rows))
        for i in range(len(headers))
    ]

    def format_row(cells):
        return " | ".join(cell.ljust(width) for cell, width in zip(cells, widths))

    print(format_row(headers))
    print("-+-".join("-" * width for width in widths))
    for row in rows:
        print(format_row(row))


def print_summary(rows: list) -> None:
    matches = sum(1 for row in rows if row[3] == "MATCH")
    over_calls = sum(1 for row in rows if row[3] == "OVER-CALL")
    under_calls = sum(1 for row in rows if row[3] == "UNDER-CALL")
    status_diffs = sum(1 for row in rows if row[3] == "STATUS-DIFF")

    print()
    print(f"Matches: {matches}/{len(rows)}")
    print(f"Over-calls (false positives): {over_calls}")
    print(f"Under-calls (false negatives): {under_calls}")
    print(f"Status mismatches: {status_diffs}")


def main() -> None:
    args = parse_args()

    pipeline_by_pattern = load_status_by_pattern(args.output)
    ground_truth_by_pattern = load_status_by_pattern(args.ground_truth)

    rows = score(pipeline_by_pattern, ground_truth_by_pattern)
    print_table(rows)
    print_summary(rows)


if __name__ == "__main__":
    main()
