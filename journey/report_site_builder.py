"""Assembles the data report-site.py needs to roll up every recorded
episode for one site_id -- across every goal and revisit -- into a single
overview page (Layer 2). Reuses each episode's own attribute results and
group_evidence.json (already written by run-attributes /
extract-group-evidence); does no measurement or judgement of its own.
"""

import json
import os
from collections import Counter
from typing import Dict, List

from journey.schema_migration import load_episode
from recorder.interactive_v2 import EPISODE_FILENAME


def _episode_summary(episode_dir: str, episode: Dict) -> Dict:
    meta = episode.get("episode") or {}
    results = (episode.get("attributes") or {}).get("results") or []
    verdict_counts = Counter(r["verdict"] for r in results)
    return {
        "episode_id": meta.get("episode_id"),
        "episode_dir": episode_dir,
        "goal": meta.get("goal"),
        "revisit_index": meta.get("revisit_index"),
        "site_domain": meta.get("site_domain"),
        "device_context": meta.get("device_context"),
        "operator": meta.get("operator"),
        "paired_episode_id": meta.get("paired_episode_id"),
        "group_evidence_path": meta.get("group_evidence_path"),
        "outcome": episode.get("outcome") or {},
        "verdict_counts": dict(verdict_counts),
        "firing_attributes": sorted(r["attribute"] for r in results if r["verdict"] == "fires"),
        "has_attributes": bool(results),
    }


def find_site_episodes(site_id: str, storage_dir: str) -> List[Dict]:
    """Every complete episode under storage_dir whose site_id matches,
    sorted by (goal, revisit_index, episode_id) so revisits of the same
    goal land next to each other."""
    if not os.path.isdir(storage_dir):
        return []
    episodes = []
    for name in sorted(os.listdir(storage_dir)):
        episode_dir = os.path.join(storage_dir, name)
        episode_json_path = os.path.join(episode_dir, EPISODE_FILENAME)
        if not os.path.isfile(episode_json_path):
            continue
        try:
            episode = load_episode(episode_json_path)
        except Exception:
            continue
        meta = episode.get("episode") or {}
        if meta.get("site_id") != site_id:
            continue
        episodes.append(_episode_summary(episode_dir, episode))

    episodes.sort(key=lambda e: (e["goal"] or "", e["revisit_index"] if e["revisit_index"] is not None else 0, e["episode_id"]))
    return episodes


def _group_evidence_summaries(episodes: List[Dict], storage_dir: str) -> List[Dict]:
    summaries = []
    seen_paths = set()
    for e in episodes:
        path = e["group_evidence_path"]
        if not path or path in seen_paths:
            continue
        seen_paths.add(path)
        full_path = os.path.join(storage_dir, path)
        if not os.path.isfile(full_path):
            continue
        with open(full_path, "r", encoding="utf-8") as f:
            summaries.append(json.load(f))
    return summaries


def build_site_report_data(site_id: str, storage_dir: str) -> Dict:
    episodes = find_site_episodes(site_id, storage_dir)
    goals = sorted({e["goal"] for e in episodes if e["goal"] is not None})
    return {
        "site_id": site_id,
        "episodes": episodes,
        "goals": goals,
        "group_evidence_summaries": _group_evidence_summaries(episodes, storage_dir),
    }
