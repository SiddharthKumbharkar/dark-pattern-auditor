"""Attribute agent framework -- see attribute_agents/base.py for the
interface and the hard rules enforced on every agent's behalf, and
attribute_agents/registry.py for the list of registered agents.

A new, small package rather than files under signals/ or journey/: these
agents consume already-computed measurements (episode.evidence,
group_evidence.json) to produce a VERDICT with severity/confidence, which
is a genuinely different kind of component than the pure measurement
extractors in signals/ -- CLAUDE.md's original four-layer list predates
this phased evidence/attribute/verdict pipeline and doesn't name a layer
for it, so this is a new top-level package rather than a forced fit into
an existing one, same reasoning as recorder/masking/ being its own
sub-package for a distinct concern.
"""
