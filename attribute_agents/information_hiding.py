"""information_hiding: was a cost, term, or condition WITHHELD from the
user until later in the flow, as opposed to a price that legitimately
grows because the user added something (shipping selected, quantity
changed, an optional add-on accepted)? A raw price_drift.increases delta
can't tell those two cases apart on its own -- that requires reading the
surrounding copy and the user's own actions in context, which is
interpretive judgement this framework's code agents don't make (Stage 2,
LLM judge).

This is an explicit stub, not a real assessment: it always returns
not_assessable with reason "requires LLM judgement -- Stage 2",
regardless of input -- including a price_drift shape that would have
fired under a naive delta-only heuristic. Do not add real logic here;
add an LLM-backed agent alongside it instead when Stage 2 lands.
"""

from typing import Dict, Optional

from attribute_agents.base import AttributeAgent, not_assessable_result
from journey.baselines import BaselineStore

AGENT_VERSION = "information_hiding_stub/1.0.0"

STUB_REASON = "requires LLM judgement — Stage 2"


def assess(episode: Dict, group_evidence: Optional[Dict], baselines: BaselineStore) -> Dict:
    return not_assessable_result(STUB_REASON)


AGENT = AttributeAgent(
    agent_id="information_hiding_stub_v1",
    attribute="information_hiding",
    agent_version=AGENT_VERSION,
    agent_type="code",
    required_signals=[],
    assess=assess,
)
