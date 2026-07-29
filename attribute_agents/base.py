"""The attribute agent interface, and the hard rules enforced on every
agent's behalf -- individual agents (attribute_agents/asymmetry.py etc.)
never implement these themselves.

An agent is an AttributeAgent instance wrapping a pure `assess` function:
    assess(episode: dict, group_evidence: dict | None, baselines: BaselineStore) -> dict
returning a PARTIAL result -- just {verdict, severity, confidence,
evidence_pointers, reasoning}. run_agent() below fills in
{attribute, agent_version, agent_type} and enforces:
  1. required_signals: if any declared dot-path resolves to null/missing/
     empty on (episode, group_evidence), the agent's assess() is never
     even called -- the framework returns not_assessable itself. This is
     the generic, structural half of "not_assessable is required when
     the necessary signal is null"; agents remain free to ALSO return
     not_assessable themselves for more nuanced insufficiency their
     declared paths can't capture (see attribute_agents/deception.py).
  2. verdict in (fires, unsure) with empty evidence_pointers is
     downgraded to "no" (severity cleared), with a warning logged.
  3. every raw result is validated against the full contract shape
     before any of the above -- a malformed agent result raises
     ContractViolation rather than being silently accepted.

Agents are pure functions of (episode, group_evidence, baselines): no
file I/O happens inside assess() or run_agent() -- the caller
(journey/attribute_runner.py) already loaded all three from disk.
"""

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from journey.baselines import BaselineStore

ATTRIBUTES = (
    "asymmetry",
    "covertness",
    "deception",
    "information_hiding",
    "restriction",
    "disparate_treatment",
    "complexity",
)
VERDICTS = ("fires", "no", "unsure", "not_assessable")
AGENT_TYPES = ("code", "llm")

AssessFn = Callable[[Dict, Optional[Dict], BaselineStore], Dict]


class ContractViolation(ValueError):
    """An agent's raw result doesn't match the required contract shape --
    a bug in the agent, not a legitimate business-logic outcome."""


@dataclass(frozen=True)
class AttributeAgent:
    agent_id: str
    attribute: str
    agent_version: str
    agent_type: str
    required_signals: List[str]
    assess: AssessFn

    def __post_init__(self):
        if self.attribute not in ATTRIBUTES:
            raise ValueError(f"unknown attribute {self.attribute!r}, must be one of {ATTRIBUTES}")
        if self.agent_type not in AGENT_TYPES:
            raise ValueError(f"unknown agent_type {self.agent_type!r}, must be one of {AGENT_TYPES}")


def not_assessable_result(reasoning: str) -> Dict:
    """Agents should use this (rather than hand-rolling the dict) for
    their own nuanced not_assessable returns, so the shape always matches
    exactly what the framework itself produces for a declared-missing signal."""
    return {"verdict": "not_assessable", "severity": None, "confidence": 0.0, "evidence_pointers": [], "reasoning": reasoning}


def no_result(reasoning: str, confidence: float = 0.7) -> Dict:
    return {"verdict": "no", "severity": None, "confidence": confidence, "evidence_pointers": [], "reasoning": reasoning}


def scale_severity(value: float, threshold_median: float, cap_multiple: float = 3.0) -> int:
    """1 at the threshold itself, 5 at cap_multiple*threshold or beyond,
    linear in between. Callers only invoke this once value has already
    been established to be at/above the threshold."""
    if threshold_median <= 0:
        return 3
    ratio = value / threshold_median
    if ratio <= 1:
        return 1
    scaled = 1 + 4 * min(1.0, (ratio - 1) / (cap_multiple - 1))
    return max(1, min(5, round(scaled)))


def _resolve_path(episode: Dict, group_evidence: Optional[Dict], path: str) -> Any:
    if path.startswith("group_evidence."):
        current: Any = group_evidence
        parts = path[len("group_evidence."):].split(".")
    else:
        current = episode
        parts = path.split(".")
    for part in parts:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (list, dict, str)) and len(value) == 0:
        return True
    return False


def _missing_signals(agent: AttributeAgent, episode: Dict, group_evidence: Optional[Dict]) -> List[str]:
    return [path for path in agent.required_signals if _is_missing(_resolve_path(episode, group_evidence, path))]


def _validate_evidence_pointer(pointer: Dict) -> None:
    if not isinstance(pointer, dict):
        raise ContractViolation(f"evidence_pointers entries must be objects, got {pointer!r}")
    for key in ("step_id", "selector", "signal"):
        if key not in pointer:
            raise ContractViolation(f"evidence_pointers entry missing {key!r}: {pointer!r}")
    if not pointer["signal"]:
        raise ContractViolation(f"evidence_pointers entry has an empty 'signal': {pointer!r}")


def _validate_raw_result(raw: Dict) -> None:
    required_keys = {"verdict", "severity", "confidence", "evidence_pointers", "reasoning"}
    missing_keys = required_keys - set(raw.keys())
    if missing_keys:
        raise ContractViolation(f"agent result missing key(s): {sorted(missing_keys)}")
    if raw["verdict"] not in VERDICTS:
        raise ContractViolation(f"invalid verdict {raw['verdict']!r}, must be one of {VERDICTS}")
    if raw["severity"] is not None and raw["severity"] not in (1, 2, 3, 4, 5):
        raise ContractViolation(f"severity must be an int 1-5 or null, got {raw['severity']!r}")
    if not isinstance(raw["confidence"], (int, float)) or not (0.0 <= raw["confidence"] <= 1.0):
        raise ContractViolation(f"confidence must be a number in [0.0, 1.0], got {raw['confidence']!r}")
    if not isinstance(raw["evidence_pointers"], list):
        raise ContractViolation("evidence_pointers must be a list")
    for pointer in raw["evidence_pointers"]:
        _validate_evidence_pointer(pointer)
    if not isinstance(raw["reasoning"], str) or not raw["reasoning"]:
        raise ContractViolation("reasoning must be a non-empty string")


def run_agent(
    agent: AttributeAgent, episode: Dict, group_evidence: Optional[Dict], baselines: BaselineStore
) -> Tuple[Dict, List[str]]:
    """Returns (result, warnings). result always matches the full 8-key
    contract; warnings is non-empty only when a hard rule corrected the
    agent's raw output."""
    warnings: List[str] = []

    missing = _missing_signals(agent, episode, group_evidence)
    if missing:
        raw = not_assessable_result(f"Required signal(s) unavailable: {', '.join(missing)}.")
    else:
        raw = agent.assess(episode, group_evidence, baselines)
        _validate_raw_result(raw)

        if raw["verdict"] in ("fires", "unsure") and not raw["evidence_pointers"]:
            warning = (
                f"{agent.agent_id}: verdict={raw['verdict']!r} with empty evidence_pointers -- "
                f"downgraded to 'no' per framework hard rule."
            )
            warnings.append(warning)
            print(f"  Warning: {warning}")
            raw = dict(raw)
            raw["verdict"] = "no"
            raw["severity"] = None

    result = {
        "attribute": agent.attribute,
        "verdict": raw["verdict"],
        "severity": raw["severity"],
        "confidence": raw["confidence"],
        "evidence_pointers": raw["evidence_pointers"],
        "reasoning": raw["reasoning"],
        "agent_version": agent.agent_version,
        "agent_type": agent.agent_type,
    }
    return result, warnings
