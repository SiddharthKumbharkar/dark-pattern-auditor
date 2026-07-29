"""Runs the registered attribute agents (attribute_agents/registry.py)
against a stored episode and writes episode.attributes (Layer 2 -- file
I/O, so this lives here rather than in attribute_agents/, which stays
pure per its own docstring: "Agents are pure functions of (episode,
group_evidence, baselines). No I/O." This module is what loads all three
from disk before handing them to run_agent().
"""

import json
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

from attribute_agents.base import run_agent
from attribute_agents.registry import get_enabled_agents
from journey.baselines import BaselineStore
from journey.schema_migration import load_episode, validate_v2
from recorder.interactive_v2 import EPISODE_FILENAME

EXTRACTOR_VERSION = "attribute_runner/1.0.0"


def _resolve_episode_json_path(path: str) -> str:
    if os.path.isdir(path):
        return os.path.join(path, EPISODE_FILENAME)
    return path


def _load_group_evidence(episode: Dict, storage_dir: str) -> Optional[Dict]:
    group_evidence_path = (episode.get("episode") or {}).get("group_evidence_path")
    if not group_evidence_path:
        return None
    full_path = os.path.join(storage_dir, group_evidence_path)
    if not os.path.isfile(full_path):
        return None
    with open(full_path, "r", encoding="utf-8") as f:
        return json.load(f)


def run_attributes(
    episode_path: str,
    storage_dir: Optional[str] = None,
    enabled_agents: Optional[List[str]] = None,
    baselines_path: Optional[str] = None,
) -> Dict:
    """Idempotent: always fully replaces episode["attributes"] (never
    merges/appends whatever was there before), so re-running against the
    same stored episode+group_evidence+baselines produces the same
    result every time -- no re-recording needed.
    """
    episode_json_path = _resolve_episode_json_path(episode_path)
    episode_dir = os.path.dirname(episode_json_path)
    if storage_dir is None:
        storage_dir = os.path.dirname(episode_dir)

    episode = load_episode(episode_json_path)
    group_evidence = _load_group_evidence(episode, storage_dir)
    baselines = BaselineStore(path=baselines_path)
    agents = get_enabled_agents(enabled_agents)

    results = []
    all_warnings: List[str] = []
    for agent in agents:
        result, warnings = run_agent(agent, episode, group_evidence, baselines)
        results.append(result)
        all_warnings.extend(warnings)

    episode["attributes"] = {
        "extractor_version": EXTRACTOR_VERSION,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "results": results,
    }

    errors = validate_v2(episode)
    if errors:
        print(f"  Warning: episode failed v2 validation after attribute assessment ({len(errors)} error(s)):")
        for error in errors:
            print(f"    - {error}")

    with open(episode_json_path, "w", encoding="utf-8") as f:
        json.dump(episode, f, indent=2)

    return episode
