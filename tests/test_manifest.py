"""Tests for journey/manifest.py -- run_manifest.json writer."""

import json
import os

from config.settings import PROJECT_ROOT, Config
from journey.manifest import MANIFEST_FILENAME, TOOL_VERSION, build_manifest, write_run_manifest


def test_build_manifest_has_required_fields():
    cfg = Config()
    manifest = build_manifest(audit_id="audit_x", config=cfg, operator="alice", project_root=os.getcwd())
    assert manifest["audit_id"] == "audit_x"
    assert manifest["operator"] == "alice"
    assert manifest["tool_version"] == TOOL_VERSION
    assert "timestamp" in manifest and manifest["timestamp"]
    assert manifest["config_snapshot"]["pipeline"]["mode"] == "both"
    assert "git_commit_hash" in manifest


def test_git_commit_hash_resolves_in_this_repo():
    cfg = Config()
    manifest = build_manifest(audit_id="audit_x", config=cfg, operator="alice", project_root=PROJECT_ROOT)
    assert len(manifest["git_commit_hash"]) == 40
    assert all(c in "0123456789abcdef" for c in manifest["git_commit_hash"])


def test_git_commit_hash_falls_back_to_unknown_outside_a_repo(tmp_path):
    cfg = Config()
    manifest = build_manifest(audit_id="audit_x", config=cfg, operator="alice", project_root=str(tmp_path))
    assert manifest["git_commit_hash"] == "unknown"


def test_write_run_manifest_creates_episode_dir_and_file(tmp_path):
    episode_dir = os.path.join(str(tmp_path), "audit_y")
    cfg = Config()
    path = write_run_manifest(episode_dir=episode_dir, audit_id="audit_y", config=cfg, operator="bob")
    assert os.path.isfile(path)
    assert path == os.path.join(episode_dir, MANIFEST_FILENAME)
    with open(path) as f:
        data = json.load(f)
    assert data["audit_id"] == "audit_y"
    assert data["operator"] == "bob"
