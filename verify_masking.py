#!/usr/bin/env python3
"""CLI: independently re-scan a STORED episode's artifacts for PII,
regardless of what the recording session itself believed at capture time.

Usage:
    python3 verify_masking.py <episode.json path, or its containing dir>

Rewrites the episode's privacy.validation_passed to match what THIS scan
found (not what the recorder believed -- this is meant to catch cases
where the recorder's own self-check was wrong or was bypassed). Exit code
0 on pass, 1 on fail (including a missing episode). If privacy.strict is
true and the scan fails, prints an explicit ABORT line -- this tool
doesn't have a "session" to abort, so "abort" means: exit nonzero and
make unmistakably clear this episode must not be used downstream.
"""

import argparse
import json
import os
import sys
from typing import Dict, List

from bs4 import BeautifulSoup

from config.settings import load_config
from recorder.masking.patterns import find_card_numbers, find_emails, find_phone_numbers


def _resolve_episode_json_path(path: str) -> str:
    if os.path.isdir(path):
        return os.path.join(path, "episode.json")
    return path


def _scan_text(text: str, location: str, findings: List[str]) -> None:
    text = text or ""
    if any(True for _ in find_card_numbers(text)):
        findings.append(f"{location}: possible card number found")
    if any(True for _ in find_emails(text)):
        findings.append(f"{location}: possible email address found")
    if any(True for _ in find_phone_numbers(text)):
        findings.append(f"{location}: possible phone number found")


def verify_masking(episode_path: str) -> List[str]:
    """Returns a list of human-readable findings (empty if clean)."""
    episode_dir = os.path.dirname(episode_path)
    with open(episode_path, "r", encoding="utf-8") as f:
        episode = json.load(f)

    findings: List[str] = []

    for step in episode.get("steps") or []:
        step_id = step.get("step_id")

        # An unmasked artifact tracked as living in the episode folder is
        # itself a finding, independent of whether it happens to contain
        # PII -- "raw unmasked artifacts must never be written" is a
        # structural rule, not just a PII-content rule.
        if step.get("screenshot_path"):
            findings.append(f"step {step_id}: screenshot_path is set -- an unmasked screenshot is tracked in the episode folder")
        if step.get("dom_snapshot_path"):
            findings.append(f"step {step_id}: dom_snapshot_path is set -- an unmasked DOM snapshot is tracked in the episode folder")

        dom_path = step.get("dom_snapshot_masked_path") or step.get("dom_snapshot_path")
        if dom_path:
            full_path = os.path.join(episode_dir, dom_path)
            if not os.path.isfile(full_path):
                findings.append(f"step {step_id}: {dom_path} does not exist on disk")
            else:
                with open(full_path, "r", encoding="utf-8") as f:
                    dom_html = f.read()
                text = BeautifulSoup(dom_html, "html.parser").get_text(" ")
                _scan_text(text, f"step {step_id} dom ({dom_path})", findings)

        _scan_text(step.get("page_url_redacted"), f"step {step_id} page_url_redacted", findings)

        for event in step.get("network_events") or []:
            _scan_text(event.get("url_redacted"), f"step {step_id} network url_redacted", findings)
            for header_name in event.get("redacted_headers") or []:
                # redacted_headers should only ever contain short header
                # NAMES (e.g. "authorization") -- a long or bearer-shaped
                # entry here would itself mean a value leaked into the name slot.
                if len(header_name) > 40 or "bearer " in header_name.lower():
                    findings.append(f"step {step_id} network: redacted_headers entry looks like a value, not a name: {header_name!r}")

        screenshot_masked_path = step.get("screenshot_masked_path")
        if screenshot_masked_path and not os.path.isfile(os.path.join(episode_dir, screenshot_masked_path)):
            findings.append(f"step {step_id}: {screenshot_masked_path} does not exist on disk")

    return findings


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Re-scan a stored episode's masked artifacts for PII.")
    parser.add_argument("episode", help="Path to an episode.json file, or its containing directory")
    parser.add_argument("--config", default=None, help="Path to config.yaml")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    episode_path = _resolve_episode_json_path(args.episode)

    if not os.path.isfile(episode_path):
        print(f"FAIL: no episode file found at {episode_path}")
        return 1

    findings = verify_masking(episode_path)
    passed = not findings

    with open(episode_path, "r", encoding="utf-8") as f:
        episode: Dict = json.load(f)
    episode.setdefault("privacy", {})["validation_passed"] = passed
    with open(episode_path, "w", encoding="utf-8") as f:
        json.dump(episode, f, indent=2)

    if passed:
        print(f"PASS {episode_path}")
        return 0

    print(f"FAIL {episode_path} ({len(findings)} finding(s))")
    for finding in findings:
        print(f"  - {finding}")

    if cfg.privacy.strict:
        print("ABORT: privacy.strict is true -- this episode must not be used downstream.")

    return 1


if __name__ == "__main__":
    sys.exit(main())
