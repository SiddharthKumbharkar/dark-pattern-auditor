"""Tests for verify_masking.py's importable core (verify_masking()) plus a
couple of subprocess-level CLI smoke tests for exit codes."""

import json
import os
import subprocess
import sys

from verify_masking import verify_masking

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _write_episode(episode_dir, steps):
    os.makedirs(episode_dir, exist_ok=True)
    with open(os.path.join(episode_dir, "episode.json"), "w", encoding="utf-8") as f:
        json.dump({"steps": steps, "privacy": {"validation_passed": True}}, f)


def test_clean_masked_dom_passes(tmp_path):
    episode_dir = str(tmp_path)
    os.makedirs(os.path.join(episode_dir, "dom"))
    with open(os.path.join(episode_dir, "dom", "step_001.html"), "w") as f:
        f.write("<html><body><p>Only 2 left in stock!</p></body></html>")

    _write_episode(
        episode_dir,
        [
            {
                "step_id": 1,
                "screenshot_path": None,
                "dom_snapshot_path": None,
                "dom_snapshot_masked_path": "dom/step_001.html",
                "screenshot_masked_path": None,
                "page_url_redacted": "https://example.com/",
                "network_events": [],
            }
        ],
    )

    findings = verify_masking(os.path.join(episode_dir, "episode.json"))
    assert findings == []


def test_leftover_email_in_masked_dom_is_caught(tmp_path):
    episode_dir = str(tmp_path)
    os.makedirs(os.path.join(episode_dir, "dom"))
    with open(os.path.join(episode_dir, "dom", "step_001.html"), "w") as f:
        f.write("<html><body><p>leaked: someone@example.com</p></body></html>")

    _write_episode(
        episode_dir,
        [
            {
                "step_id": 1,
                "screenshot_path": None,
                "dom_snapshot_path": None,
                "dom_snapshot_masked_path": "dom/step_001.html",
                "screenshot_masked_path": None,
                "page_url_redacted": "https://example.com/",
                "network_events": [],
            }
        ],
    )

    findings = verify_masking(os.path.join(episode_dir, "episode.json"))
    assert len(findings) == 1
    assert "email" in findings[0]


def test_unmasked_screenshot_path_present_is_flagged(tmp_path):
    episode_dir = str(tmp_path)
    _write_episode(
        episode_dir,
        [
            {
                "step_id": 1,
                "screenshot_path": "screenshots/step_001.png",  # should never be set
                "dom_snapshot_path": None,
                "dom_snapshot_masked_path": None,
                "screenshot_masked_path": None,
                "page_url_redacted": "https://example.com/",
                "network_events": [],
            }
        ],
    )

    findings = verify_masking(os.path.join(episode_dir, "episode.json"))
    assert any("screenshot_path is set" in f for f in findings)


def test_leaked_pii_in_network_url_is_caught(tmp_path):
    episode_dir = str(tmp_path)
    _write_episode(
        episode_dir,
        [
            {
                "step_id": 1,
                "screenshot_path": None,
                "dom_snapshot_path": None,
                "dom_snapshot_masked_path": None,
                "screenshot_masked_path": None,
                "page_url_redacted": "https://example.com/",
                "network_events": [
                    {"url_redacted": "https://api.example.com/track?email=someone@example.com", "redacted_headers": []}
                ],
            }
        ],
    )

    findings = verify_masking(os.path.join(episode_dir, "episode.json"))
    assert any("network url_redacted" in f for f in findings)


def test_missing_masked_dom_file_on_disk_is_caught(tmp_path):
    episode_dir = str(tmp_path)
    _write_episode(
        episode_dir,
        [
            {
                "step_id": 1,
                "screenshot_path": None,
                "dom_snapshot_path": None,
                "dom_snapshot_masked_path": "dom/does_not_exist.html",
                "screenshot_masked_path": None,
                "page_url_redacted": "https://example.com/",
                "network_events": [],
            }
        ],
    )

    findings = verify_masking(os.path.join(episode_dir, "episode.json"))
    assert any("does not exist on disk" in f for f in findings)


# -- CLI-level: exit codes and validation_passed rewriting ------------------


def test_cli_exits_zero_and_prints_pass_for_clean_episode(tmp_path):
    episode_dir = str(tmp_path)
    os.makedirs(os.path.join(episode_dir, "dom"))
    with open(os.path.join(episode_dir, "dom", "step_001.html"), "w") as f:
        f.write("<html><body><p>Only 2 left!</p></body></html>")
    _write_episode(
        episode_dir,
        [
            {
                "step_id": 1,
                "screenshot_path": None,
                "dom_snapshot_path": None,
                "dom_snapshot_masked_path": "dom/step_001.html",
                "screenshot_masked_path": None,
                "page_url_redacted": "https://example.com/",
                "network_events": [],
            }
        ],
    )

    result = subprocess.run(
        [sys.executable, os.path.join(REPO_ROOT, "verify_masking.py"), episode_dir],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "PASS" in result.stdout

    with open(os.path.join(episode_dir, "episode.json")) as f:
        assert json.load(f)["privacy"]["validation_passed"] is True


def test_cli_exits_nonzero_and_prints_fail_for_dirty_episode(tmp_path):
    episode_dir = str(tmp_path)
    os.makedirs(os.path.join(episode_dir, "dom"))
    with open(os.path.join(episode_dir, "dom", "step_001.html"), "w") as f:
        f.write("<html><body><p>call 555-123-4567</p></body></html>")
    _write_episode(
        episode_dir,
        [
            {
                "step_id": 1,
                "screenshot_path": None,
                "dom_snapshot_path": None,
                "dom_snapshot_masked_path": "dom/step_001.html",
                "screenshot_masked_path": None,
                "page_url_redacted": "https://example.com/",
                "network_events": [],
            }
        ],
    )

    result = subprocess.run(
        [sys.executable, os.path.join(REPO_ROOT, "verify_masking.py"), episode_dir],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "FAIL" in result.stdout

    with open(os.path.join(episode_dir, "episode.json")) as f:
        assert json.load(f)["privacy"]["validation_passed"] is False
