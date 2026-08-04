"""covertness: is the negative/reject option DELIBERATELY hidden or
disguised, as distinct from asymmetry.py's purely visual imbalance
check? Judging INTENT/covertness from static signals alone (contrast,
fold position) is exactly the kind of interpretive call this framework's
code agents are not allowed to make -- a below-the-fold negative option
can be innocent page layout as easily as it can be concealment, and
telling those apart needs the kind of contextual reading only an LLM
judge can do (Stage 2 of this project).

This is an explicit stub, not a real assessment: it always returns
not_assessable with reason "requires LLM judgement -- Stage 2",
regardless of input -- including inputs that would have fired under a
naive visual-only heuristic. Do not add real logic here; add an
LLM-backed agent alongside it instead when Stage 2 lands.
"""

from typing import Dict, Optional

from attribute_agents.base import AttributeAgent, STAGE2_STUB_REASON, not_assessable_result
from journey.baselines import BaselineStore

AGENT_VERSION = "covertness_stub/1.0.0"


def assess(episode: Dict, group_evidence: Optional[Dict], baselines: BaselineStore) -> Dict:
    return not_assessable_result(STAGE2_STUB_REASON)


AGENT = AttributeAgent(
    agent_id="covertness_stub_v1",
    attribute="covertness",
    agent_version=AGENT_VERSION,
    agent_type="code",
    required_signals=[],
    assess=assess,
)
