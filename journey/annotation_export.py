"""Flat, one-row-per-(episode, attribute) export for human annotation.
Each row carries the SAME per-attribute evidence relevance view
llm/payload_builder.py's --role attribute payload uses
(build_attribute_evidence_summary, reused directly rather than
re-derived, so the two views can never drift apart), the code agent's
verdict, and empty human_verdict/annotator_id columns for a human
labeller to fill in by hand -- this module never writes into those two
columns itself.
"""

import os
from typing import Dict, List

from attribute_agents.base import ATTRIBUTES
from journey.schema_migration import load_episode
from llm.payload_builder import build_attribute_evidence_summary, load_group_evidence
from recorder.interactive_v2 import EPISODE_FILENAME

ANNOTATION_ROW_FIELDS = [
    "episode_id", "attribute", "evidence_summary",
    "code_verdict", "code_severity", "code_confidence", "code_reasoning",
    "human_verdict", "annotator_id",
]


def _resolve_episode_json_path(path: str) -> str:
    if os.path.isdir(path):
        return os.path.join(path, EPISODE_FILENAME)
    return path


def _rows_for_episode(episode_path: str, storage_dir: str) -> List[Dict]:
    episode_json_path = _resolve_episode_json_path(episode_path)
    episode_dir = os.path.dirname(episode_json_path)
    if storage_dir is None:
        storage_dir = os.path.dirname(episode_dir)

    episode = load_episode(episode_json_path)
    episode_id = episode["episode"]["episode_id"]
    group_evidence = load_group_evidence(episode, storage_dir)

    rows = []
    for attribute in ATTRIBUTES:
        summary, _step_ids = build_attribute_evidence_summary(episode, group_evidence, attribute)
        code_result = summary["code_agent_result"]
        rows.append({
            "episode_id": episode_id,
            "attribute": attribute,
            "evidence_summary": {
                "relevant_evidence": summary["relevant_evidence"],
                "relevant_group_evidence": summary["relevant_group_evidence"],
            },
            "code_verdict": code_result["verdict"] if code_result else None,
            "code_severity": code_result["severity"] if code_result else None,
            "code_confidence": code_result["confidence"] if code_result else None,
            "code_reasoning": code_result["reasoning"] if code_result else None,
            "human_verdict": "",
            "annotator_id": "",
        })
    return rows


def export_for_annotation(episode_paths: List[str], storage_dir: str) -> List[Dict]:
    """Idempotent/pure: reads whatever is currently stored for each
    episode and returns a fresh row list every call -- writing the result
    to disk (CSV or JSON) is the CLI's job, not this function's."""
    rows: List[Dict] = []
    for path in episode_paths:
        rows.extend(_rows_for_episode(path, storage_dir))
    return rows
