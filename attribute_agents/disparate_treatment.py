"""disparate_treatment: did a linked flow (e.g. signup vs cancel) treat
this episode's path differently from its pair in a way that specifically
DISADVANTAGES the user, as opposed to a structural difference that's
simply inherent to the two tasks being different (a cancellation flow
legitimately asking a confirmation question a signup flow never needs
to)? A raw step/click/field ratio deviation can't distinguish "harder
because it's deliberately obstructed" from "harder because it's a
different, more involved task" -- that distinction needs contextual
judgement, which is Stage 2 (LLM judge) territory, not this framework's
code agents.

This is an explicit stub, not a real assessment: it always returns
not_assessable with reason "requires LLM judgement -- Stage 2",
regardless of input -- including a paired_flow_comparison shape that
would have fired under a naive ratio-deviation heuristic. Do not add
real logic here; add an LLM-backed agent alongside it instead when
Stage 2 lands.
"""

from typing import Dict, Optional

from attribute_agents.base import AttributeAgent, STAGE2_STUB_REASON, not_assessable_result
from journey.baselines import BaselineStore

AGENT_VERSION = "disparate_treatment_stub/1.0.0"


def assess(episode: Dict, group_evidence: Optional[Dict], baselines: BaselineStore) -> Dict:
    return not_assessable_result(STAGE2_STUB_REASON)


AGENT = AttributeAgent(
    agent_id="disparate_treatment_stub_v1",
    attribute="disparate_treatment",
    agent_version=AGENT_VERSION,
    agent_type="code",
    required_signals=[],
    assess=assess,
)
