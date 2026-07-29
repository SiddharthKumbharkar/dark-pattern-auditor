"""Tests for the unified entry point (dpa.py) and its structured logging
(logging_setup.py). Exercises real delegation to real command modules
(list-goals, run-attributes against a real recorded/processed episode,
etc.) end to end via subprocess, plus direct checks of the JSONL log
format.
"""

import json
import os
import subprocess
import sys

from config.settings import Config
from journey.attribute_runner import run_attributes
from journey.evidence_extractor import extract_evidence
from logging_setup import JSONLFormatter, configure_logging, get_logger
from recorder.interactive_v2 import InteractiveRecorderV2

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PAGE_HTML = "<!DOCTYPE html><html><body><h1>Product</h1></body></html>"


def _run_dpa(args, **kwargs):
    return subprocess.run(
        [sys.executable, os.path.join(REPO_ROOT, "dpa.py"), *args],
        capture_output=True, text=True, **kwargs,
    )


# -- command listing / dispatch ------------------------------------------


def test_no_command_prints_help_and_exits_nonzero():
    result = _run_dpa([])
    assert result.returncode == 1
    assert "Available commands" in result.stdout
    assert "run-attributes" in result.stdout


def test_explicit_help_flag_prints_help_and_exits_zero():
    result = _run_dpa(["--help"])
    assert result.returncode == 0
    assert "Available commands" in result.stdout


def test_unknown_command_lists_available_commands_and_exits_nonzero():
    result = _run_dpa(["not-a-real-command"])
    assert result.returncode == 1
    assert "unknown command" in result.stdout
    assert "run-attributes" in result.stdout


def test_every_registered_command_help_delegates_without_crashing():
    from dpa import COMMAND_TABLE
    for name in COMMAND_TABLE:
        if name == "serve":
            continue  # launches a live server; not argparse-only
        result = _run_dpa([name, "--help"])
        assert result.returncode == 0, f"{name} --help failed: {result.stderr}"
        assert "usage:" in result.stdout.lower(), f"{name} --help printed no usage line"


def test_command_specific_help_matches_running_the_script_directly():
    via_dpa = _run_dpa(["run-attributes", "--help"])
    direct = subprocess.run(
        [sys.executable, os.path.join(REPO_ROOT, "run_attributes.py"), "--help"],
        capture_output=True, text=True,
    )
    # Everything except the usage line's program name must match verbatim
    # (dpa.py deliberately rewrites "usage: run_attributes.py ..." to
    # "usage: dpa.py run-attributes ..." so the line reflects how the
    # command was actually invoked -- see dpa.py's sys.argv[0] swap).
    direct_body = direct.stdout.split("\n", 1)[1]
    via_dpa_body = via_dpa.stdout.split("usage: dpa.py run-attributes", 1)[1]
    assert direct_body.split("episode", 1)[1] in via_dpa_body
    assert "usage: dpa.py run-attributes [-h] [--agents AGENTS] [--config CONFIG] episode" in via_dpa.stdout


# -- record.py subcommand flattening --------------------------------------


def test_list_goals_delegates_to_record_module(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(f"output:\n  root: {tmp_path / 'storage'}\n")
    result = _run_dpa(["--log-file", str(tmp_path / "log.jsonl"), "list-goals", "--config", str(config_path)])
    assert result.returncode == 0
    assert "purchase_cheapest" in result.stdout


def test_list_episodes_delegates_to_record_module(tmp_path):
    storage_dir = tmp_path / "storage"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(f"output:\n  root: {storage_dir}\n")
    result = _run_dpa(["--log-file", str(tmp_path / "log.jsonl"), "list-episodes", "--config", str(config_path)])
    assert result.returncode == 0
    assert "no episodes recorded yet" in result.stdout


# -- real pipeline delegation ----------------------------------------------


def _record(storage_dir, episode_id, site_url):
    rec = InteractiveRecorderV2(
        storage_dir=storage_dir, episode_id=episode_id, site_url=site_url,
        site_domain="localhost", sector="ecommerce", goal_id="purchase_cheapest",
        goal_description="dpa cli e2e test", operator="test-operator", config=Config(),
    )
    rec.launch(headless=True)
    try:
        rec._poll_tick()
    finally:
        rec._teardown_browser()
        rec._cleanup_raw_artifacts()
    rec.finalize()
    return rec.episode_dir


def test_run_attributes_via_dpa_matches_direct_invocation(tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    (site / "page.html").write_text(PAGE_HTML, encoding="utf-8")
    storage_dir = str(tmp_path / "storage")

    episode_dir = _record(storage_dir, "episode_dpa_cli", (site / "page.html").as_uri())
    extract_evidence(episode_dir)

    config_path = tmp_path / "config.yaml"
    config_path.write_text(f"output:\n  root: {storage_dir}\n")

    result = _run_dpa(["run-attributes", episode_dir, "--config", str(config_path)])
    assert result.returncode == 0
    assert "OK" in result.stdout
    assert os.path.isfile(os.path.join(episode_dir, "episode.json"))


def test_report_command_via_dpa_builds_real_html(tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    (site / "page.html").write_text(PAGE_HTML, encoding="utf-8")
    storage_dir = str(tmp_path / "storage")

    episode_dir = _record(storage_dir, "episode_dpa_report", (site / "page.html").as_uri())
    extract_evidence(episode_dir)
    run_attributes(episode_dir, storage_dir=storage_dir)

    result = _run_dpa(["report", episode_dir])
    assert result.returncode == 0
    report_path = os.path.join(episode_dir, "report.html")
    assert os.path.isfile(report_path)
    assert "<html" in open(report_path, encoding="utf-8").read()


# -- structured logging ----------------------------------------------


def test_jsonl_log_has_lifecycle_events_for_a_real_command(tmp_path):
    log_path = tmp_path / "log.jsonl"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(f"output:\n  root: {tmp_path / 'storage'}\n")

    result = _run_dpa(["--log-file", str(log_path), "list-goals", "--config", str(config_path)])
    assert result.returncode == 0
    assert log_path.is_file()

    lines = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 2
    assert lines[0]["message"] == "command started: list-goals"
    assert lines[0]["command"] == "list-goals"
    assert lines[1]["message"] == "command finished: list-goals"
    assert "duration_seconds" in lines[1]
    for line in lines:
        assert line["level"] == "INFO"
        assert line["logger"] == "dpa"
        assert "timestamp" in line


def test_unknown_command_is_logged_as_a_warning(tmp_path):
    log_path = tmp_path / "log.jsonl"
    result = _run_dpa(["--log-file", str(log_path), "not-a-real-command"])
    assert result.returncode == 1
    lines = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert any(l["level"] == "WARNING" and "unknown command" in l["message"] for l in lines)


def test_invalid_log_level_is_rejected_cleanly(tmp_path):
    result = _run_dpa(["--log-level", "NOT_A_LEVEL", "list-goals"])
    assert result.returncode == 1
    assert "FAIL" in result.stdout


def test_human_readable_stdout_and_json_file_stay_separate(tmp_path):
    log_path = tmp_path / "log.jsonl"
    result = _run_dpa(["--log-file", str(log_path), "list-goals"])
    # stdout has human-readable "[INFO] ..." lines, never raw JSON.
    for line in result.stdout.splitlines():
        if "[INFO]" in line or "[WARNING]" in line:
            assert not line.strip().startswith("{")
    # the file, conversely, is strictly JSON lines.
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            json.loads(line)  # raises if not valid JSON


# -- logging_setup.py direct unit tests -----------------------------------


def test_configure_logging_is_idempotent_no_duplicate_handlers(tmp_path):
    log_path = str(tmp_path / "a.jsonl")
    logger1 = configure_logging(log_file=log_path)
    logger2 = configure_logging(log_file=log_path)
    assert logger1 is logger2
    assert len(logger2.handlers) == 2  # file + stream, not accumulating


def test_jsonl_formatter_includes_extra_fields():
    import logging
    formatter = JSONLFormatter()
    record = logging.LogRecord("dpa", logging.INFO, __file__, 1, "hello", (), None)
    record.extra_fields = {"command": "foo", "exit_code": 0}
    parsed = json.loads(formatter.format(record))
    assert parsed["message"] == "hello"
    assert parsed["command"] == "foo"
    assert parsed["exit_code"] == 0


def test_get_logger_returns_the_same_named_logger():
    assert get_logger().name == "dpa"
