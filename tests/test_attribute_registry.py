import pytest

from attribute_agents.base import ATTRIBUTES
from attribute_agents.registry import ALL_AGENTS, get_enabled_agents


def test_all_seven_attributes_have_a_registered_agent():
    covered = {agent.attribute for agent in ALL_AGENTS}
    assert covered == set(ATTRIBUTES)


def test_agent_ids_are_unique():
    ids = [agent.agent_id for agent in ALL_AGENTS]
    assert len(ids) == len(set(ids))


def test_none_enables_every_agent():
    assert get_enabled_agents(None) == ALL_AGENTS


def test_explicit_list_restricts_to_named_agents():
    enabled = get_enabled_agents(["asymmetry_code_v1", "complexity_code_v1"])
    assert [a.agent_id for a in enabled] == ["asymmetry_code_v1", "complexity_code_v1"]


def test_unknown_agent_id_raises():
    with pytest.raises(ValueError):
        get_enabled_agents(["not_a_real_agent"])


def test_empty_list_disables_everything():
    assert get_enabled_agents([]) == []
