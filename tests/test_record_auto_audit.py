"""record.py's --auto-audit flag: the fail-fast API-key check (before the
browser ever launches) and the post-session hand-off into auto_audit.main().
A real headed browser session isn't exercised here (record.py's own
recorder always launches headed, by design -- see CLAUDE.md's interactive
mode rules -- so a real end-to-end run isn't appropriate for the automated
suite); InteractiveRecorderV2 and auto_audit.main are swapped out for
lightweight stand-ins so the actual NEW control flow in cmd_record() is
exercised for real, without a browser popping up or spending any money.
"""

import os

import pytest

import auto_audit
import record


class _FakeRecorder:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.started = False
        _FakeRecorder.instances.append(self)

    def start(self):
        self.started = True
        return {}


def _base_args():
    return [
        "record", "--site", "https://example.com", "--goal", "purchase_cheapest",
        "--operator", "test-operator",
    ]


@pytest.fixture(autouse=True)
def _reset_fake_recorder():
    _FakeRecorder.instances.clear()
    yield
    _FakeRecorder.instances.clear()


def test_missing_api_key_fails_before_the_browser_launches(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # cmd_record's own load_dotenv() would otherwise re-populate the key
    # from this developer machine's real .env file, defeating the "key is
    # genuinely absent" scenario this test needs -- stub it out.
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: None)
    monkeypatch.setattr(record, "InteractiveRecorderV2", _FakeRecorder)

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(f"output:\n  root: {tmp_path / 'storage'}\n", encoding="utf-8")

    exit_code = record.main(_base_args() + ["--auto-audit", "--config", str(cfg_path)])

    assert exit_code == 1
    assert _FakeRecorder.instances == []  # never constructed -- browser never launched


def test_auto_audit_flag_hands_off_to_auto_audit_after_session_ends(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key-not-real")
    monkeypatch.setattr(record, "InteractiveRecorderV2", _FakeRecorder)

    captured = {}

    def _fake_auto_audit_main(argv):
        captured["argv"] = argv
        return 0

    monkeypatch.setattr(auto_audit, "main", _fake_auto_audit_main)

    storage_dir = tmp_path / "storage"
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(f"output:\n  root: {storage_dir}\n", encoding="utf-8")

    exit_code = record.main(
        _base_args() + ["--auto-audit", "--model", "claude-haiku-4-5", "--config", str(cfg_path)]
    )

    assert exit_code == 0
    assert len(_FakeRecorder.instances) == 1
    assert _FakeRecorder.instances[0].started is True

    episode_dir = captured["argv"][0]
    assert episode_dir.startswith(str(storage_dir))
    assert "--model" in captured["argv"] and "claude-haiku-4-5" in captured["argv"]
    assert "--config" in captured["argv"] and str(cfg_path) in captured["argv"]


def test_without_auto_audit_flag_never_touches_auto_audit(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)  # would fail the guard if it were even checked
    monkeypatch.setattr(record, "InteractiveRecorderV2", _FakeRecorder)

    called = []
    monkeypatch.setattr(auto_audit, "main", lambda argv: called.append(argv) or 0)

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(f"output:\n  root: {tmp_path / 'storage'}\n", encoding="utf-8")

    exit_code = record.main(_base_args() + ["--config", str(cfg_path)])

    assert exit_code == 0
    assert called == []
    assert len(_FakeRecorder.instances) == 1
