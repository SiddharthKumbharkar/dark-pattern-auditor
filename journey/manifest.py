"""Writes run_manifest.json into an episode folder (Layer 2).

Every stored episode carries a manifest recording which code, which
config, and who ran it -- so it is reproducible without relying on
external state (git log, an operator's memory, etc.).
"""

import json
import os
import subprocess
from datetime import datetime, timezone
from typing import Any, Dict

from config.settings import PROJECT_ROOT, TOOL_VERSION, Config

MANIFEST_FILENAME = "run_manifest.json"


def _git_commit_hash(project_root: str) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def build_manifest(
    audit_id: str, config: Config, operator: str, project_root: str = PROJECT_ROOT
) -> Dict[str, Any]:
    return {
        "audit_id": audit_id,
        "git_commit_hash": _git_commit_hash(project_root),
        "tool_version": TOOL_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "operator": operator,
        "config_snapshot": config.to_dict(),
    }


def write_run_manifest(
    episode_dir: str,
    audit_id: str,
    config: Config,
    operator: str,
    project_root: str = PROJECT_ROOT,
) -> str:
    os.makedirs(episode_dir, exist_ok=True)
    manifest = build_manifest(audit_id, config, operator, project_root)
    manifest_path = os.path.join(episode_dir, MANIFEST_FILENAME)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    return manifest_path
