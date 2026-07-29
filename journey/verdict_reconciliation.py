"""Reconciles code-agent verdicts (episode.attributes.results,
agent_type="code") against manually-ingested LLM verdicts
(episode.mechanism_verdict.entries, role="attribute") for the same
episode, one row per attribute.

This comparison is a first-class output of the audit pipeline, not a
debugging aid: the set of attributes where the two sides disagree is
exactly what a human reviewer needs to look at next -- either the code
agent's threshold-based measurement missed something contextual, or the
LLM over-read something the raw evidence doesn't actually support.
"""

from typing import Dict, List, Optional

from attribute_agents.base import ATTRIBUTES


def _find_code_result(episode: Dict, attribute: str) -> Optional[Dict]:
    results = (episode.get("attributes") or {}).get("results") or []
    matches = [r for r in results if r["attribute"] == attribute and r["agent_type"] == "code"]
    return matches[0] if matches else None


def _find_llm_entry(episode: Dict, attribute: str) -> Optional[Dict]:
    entries = (episode.get("mechanism_verdict") or {}).get("entries") or []
    matches = [e for e in entries if e["role"] == "attribute" and e["attribute"] == attribute]
    return matches[0] if matches else None


def _notes(code_verdict: Optional[str], code_severity, llm_verdict: Optional[str], llm_severity) -> str:
    if code_verdict is None and llm_verdict is None:
        return "no code verdict yet (run-attributes); no LLM verdict yet (ingest-response)"
    if code_verdict is None:
        return "no code verdict yet (run-attributes)"
    if llm_verdict is None:
        return "no LLM verdict yet (ingest-response)"
    if code_verdict != llm_verdict:
        return f"code says {code_verdict!r}, LLM says {llm_verdict!r}"
    if code_verdict == "not_assessable":
        return "both not_assessable -- neither side could assess this attribute"
    if code_severity != llm_severity:
        return f"verdict agrees but severity differs (code={code_severity}, llm={llm_severity})"
    return ""


def compare_verdicts(episode: Dict) -> List[Dict]:
    """One row per attribute in attribute_agents.base.ATTRIBUTES order.
    agree is True/False when both sides have a verdict, None when either
    side hasn't been produced yet (that is not itself a disagreement --
    it's missing data, kept distinct so a reviewer doesn't conflate the
    two)."""
    rows = []
    for attribute in ATTRIBUTES:
        code_result = _find_code_result(episode, attribute)
        llm_entry = _find_llm_entry(episode, attribute)
        llm_response = llm_entry["raw_response"] if llm_entry else None

        code_verdict = code_result["verdict"] if code_result else None
        code_severity = code_result["severity"] if code_result else None
        code_confidence = code_result["confidence"] if code_result else None
        code_reasoning = code_result["reasoning"] if code_result else None

        llm_verdict = llm_response["verdict"] if llm_response else None
        llm_severity = llm_response["severity"] if llm_response else None
        llm_confidence = llm_response["confidence"] if llm_response else None
        llm_reasoning = llm_response["reasoning"] if llm_response else None

        agree = None if (code_verdict is None or llm_verdict is None) else (code_verdict == llm_verdict)

        rows.append({
            "attribute": attribute,
            "code_verdict": code_verdict,
            "code_severity": code_severity,
            "code_confidence": code_confidence,
            "code_reasoning": code_reasoning,
            "llm_verdict": llm_verdict,
            "llm_severity": llm_severity,
            "llm_confidence": llm_confidence,
            "llm_reasoning": llm_reasoning,
            "agree": agree,
            "notes": _notes(code_verdict, code_severity, llm_verdict, llm_severity),
        })
    return rows
