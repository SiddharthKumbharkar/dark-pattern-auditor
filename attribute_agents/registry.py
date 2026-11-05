"""The list of registered attribute agents, and config-driven
enable/disable (Config.attributes.enabled_agents). Adding a new agent
(code or LLM-backed) means adding it to ALL_AGENTS here -- nothing else
in the framework needs to change.
"""

from typing import List, Optional

from attribute_agents.asymmetry import AGENT as ASYMMETRY_AGENT
from attribute_agents.base import AttributeAgent
from attribute_agents.complexity import AGENT as COMPLEXITY_AGENT
from attribute_agents.covertness import AGENT as COVERTNESS_AGENT
from attribute_agents.deception import AGENT as DECEPTION_AGENT
from attribute_agents.disparate_treatment import AGENT as DISPARATE_TREATMENT_AGENT
from attribute_agents.information_hiding import AGENT as INFORMATION_HIDING_AGENT
from attribute_agents.restriction import AGENT as RESTRICTION_AGENT

ALL_AGENTS: List[AttributeAgent] = [
    ASYMMETRY_AGENT,
    COVERTNESS_AGENT,
    DECEPTION_AGENT,
    INFORMATION_HIDING_AGENT,
    RESTRICTION_AGENT,
    DISPARATE_TREATMENT_AGENT,
    COMPLEXITY_AGENT,
]

_AGENTS_BY_ID = {agent.agent_id: agent for agent in ALL_AGENTS}

assert len(_AGENTS_BY_ID) == len(ALL_AGENTS), "duplicate agent_id in ALL_AGENTS"


def get_enabled_agents(enabled_agents: Optional[List[str]]) -> List[AttributeAgent]:
    """enabled_agents=None means every registered agent runs (the
    Config.attributes.enabled_agents default); an explicit list restricts
    to exactly those agent_ids, raising on an unknown one rather than
    silently ignoring a typo."""
    if enabled_agents is None:
        return list(ALL_AGENTS)

    unknown = set(enabled_agents) - set(_AGENTS_BY_ID)
    if unknown:
        raise ValueError(f"unknown agent_id(s) in attributes.enabled_agents: {sorted(unknown)}")

    return [_AGENTS_BY_ID[agent_id] for agent_id in enabled_agents]
