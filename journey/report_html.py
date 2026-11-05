"""Renders journey/report_builder.py's data dict into a single,
self-contained HTML file -- screenshots embedded as base64 data URIs, no
external assets, no CDN scripts, so the report is one file you can email
or archive. No templating engine dependency: plain Python string
building, with every piece of episode-derived text passed through
html.escape() before insertion (defense in depth -- this is a local tool,
but nothing stops a recorded page's text from containing "<script>").
"""

import json
from html import escape
from typing import Dict, List, Optional

_CSS = """
:root { color-scheme: light dark; }
body { font-family: -apple-system, Segoe UI, Helvetica, Arial, sans-serif; margin: 0; padding: 2rem;
       background: #fff; color: #111; line-height: 1.5; }
@media (prefers-color-scheme: dark) { body { background: #14161a; color: #e8e8e8; } }
h1 { font-size: 1.4rem; margin-bottom: 0.25rem; }
h2 { font-size: 1.15rem; margin-top: 2.5rem; border-bottom: 1px solid #8884; padding-bottom: 0.3rem; }
.meta-table, .evidence-table { border-collapse: collapse; width: 100%; margin: 0.75rem 0 1.5rem; font-size: 0.9rem; }
.meta-table td, .evidence-table td, .evidence-table th {
  border: 1px solid #8884; padding: 0.35rem 0.6rem; text-align: left; vertical-align: top; }
.evidence-table th { background: #8882; }
.meta-table td:first-child { font-weight: 600; white-space: nowrap; }
.filmstrip { display: flex; flex-wrap: wrap; gap: 1.25rem; }
.filmstrip-step { border: 1px solid #8884; border-radius: 8px; padding: 0.6rem; width: 340px; }
.filmstrip-step h3 { margin: 0 0 0.4rem; font-size: 0.95rem; }
.screenshot-wrap { position: relative; width: 100%; overflow: hidden; border-radius: 4px; }
.screenshot-wrap img { display: block; width: 100%; height: auto; }
.bbox { position: absolute; border: 2px solid; border-radius: 2px; pointer-events: auto; box-sizing: border-box; }
.bbox.fires { border-color: #e5484d; box-shadow: 0 0 0 1px #e5484d55; }
.bbox.unsure { border-color: #f5a623; box-shadow: 0 0 0 1px #f5a62355; }
.step-meta { font-size: 0.78rem; opacity: 0.75; margin-top: 0.4rem; word-break: break-word; }
.capture-error { color: #e5484d; font-weight: 600; }
.attribute-card { border: 1px solid #8884; border-radius: 8px; padding: 0.9rem 1.1rem; margin-bottom: 0.9rem; }
.attribute-card h3 { margin: 0 0 0.3rem; font-size: 1.02rem; }
.badge { display: inline-block; padding: 0.1rem 0.55rem; border-radius: 999px; font-size: 0.78rem; font-weight: 600; }
.badge.fires { background: #e5484d22; color: #e5484d; }
.badge.unsure { background: #f5a62322; color: #b5750a; }
.badge.no { background: #30a46c22; color: #227a51; }
.badge.not_assessable { background: #8884; color: #666; }
.pointer-list { margin: 0.5rem 0 0; padding-left: 1.2rem; font-size: 0.88rem; }
.pointer-list li { margin-bottom: 0.2rem; }
.reasoning { font-size: 0.9rem; margin-top: 0.4rem; }
code { background: #8882; padding: 0.05rem 0.3rem; border-radius: 3px; font-size: 0.85em; }
.mechanism-entry { border: 1px solid #8884; border-radius: 8px; padding: 0.9rem 1.1rem; margin-bottom: 0.9rem; }
.section-empty { opacity: 0.6; font-style: italic; }
.episode-table { border-collapse: collapse; width: 100%; margin: 0.75rem 0 1.5rem; font-size: 0.88rem; }
.episode-table td, .episode-table th {
  border: 1px solid #8884; padding: 0.4rem 0.6rem; text-align: left; vertical-align: top; }
.episode-table th { background: #8882; }
.fires-list span { display: inline-block; background: #e5484d22; color: #e5484d; border-radius: 999px;
  padding: 0.05rem 0.5rem; font-size: 0.78rem; margin: 0.1rem 0.15rem 0.1rem 0; }
.region-card { border: 1px solid #8884; border-radius: 8px; padding: 0.9rem 1.1rem; margin-bottom: 1rem;
  display: flex; gap: 1rem; flex-wrap: wrap; }
.region-card h3 { margin: 0 0 0.5rem; font-size: 1.05rem; width: 100%; }
.region-thumb { width: 220px; flex-shrink: 0; }
.region-thumb-empty { width: 220px; flex-shrink: 0; opacity: 0.6; font-style: italic; font-size: 0.85rem; }
.region-body { flex: 1; min-width: 240px; }
.fired-attr, .unsure-attr { margin-bottom: 0.3rem; font-size: 0.9rem; }
.unsure-attr { opacity: 0.85; }
.no-element { opacity: 0.65; font-style: italic; }
.shared-element { border: 1px solid #e5484d55; background: #e5484d11; border-radius: 6px;
  padding: 0.5rem 0.7rem; margin-bottom: 0.5rem; font-size: 0.9rem; }
.shared-element strong { color: #e5484d; }
.likely-pattern { font-size: 0.9rem; }
.assessment { font-size: 0.88rem; opacity: 0.9; }
.badge.strength-strong { background: #e5484d22; color: #e5484d; }
.badge.strength-moderate { background: #f5a62322; color: #b5750a; }
.badge.strength-weak { background: #8884; color: #666; }
.overall-banner { border: 1px solid #8884; border-radius: 8px; padding: 0.9rem 1.1rem; margin-bottom: 1rem; }
.overall-banner.verdict-dark_patterns_present { border-left: 4px solid #e5484d; }
.overall-banner.verdict-inconclusive { border-left: 4px solid #f5a623; }
.overall-banner.verdict-no_dark_patterns_found { border-left: 4px solid #30a46c; }
.coverage-list { margin: 0; padding-left: 1.1rem; }
.coverage-list li { margin-bottom: 0.4rem; }
.urgency-flag { border: 1px solid #f5a62355; background: #f5a62311; border-radius: 6px;
  padding: 0.6rem 0.8rem; margin: 0.6rem 0 1rem; font-size: 0.9rem; }
.urgency-flag strong:first-child { color: #b5750a; }
"""


def _is_stub(section: Dict) -> bool:
    from attribute_agents.base import STAGE2_STUB_REASON

    return section.get("agent_type") == "code" and section.get("reasoning") == STAGE2_STUB_REASON


def _badge(section: Dict) -> str:
    """Three distinct not_assessable-shaped states need three distinct
    labels, or "not_assessable" reads like "skipped" across the board:
      - verdict=="no": a real agent ran and concluded clean -- "checked,
        no evidence found" is reserved for exactly this case.
      - verdict=="not_assessable" and it's a genuine stub (covertness/
        information_hiding/disparate_treatment before their Stage-2 pass):
        never even ran -- "not assessed -- pending Stage 2".
      - verdict=="not_assessable" for any other reason (a real agent ran,
        the RIGHT KIND of evidence just wasn't there): "checked --
        insufficient evidence", distinct from both of the above.
    fires/unsure read fine as their raw verdict already."""
    verdict = section["verdict"]
    if verdict == "no":
        label = "checked, no evidence found"
    elif verdict == "not_assessable" and _is_stub(section):
        label = "not assessed — pending Stage 2"
    elif verdict == "not_assessable":
        label = "checked — insufficient evidence"
    else:
        label = verdict
    return f'<span class="badge {escape(verdict)}">{escape(label)}</span>'


def _meta_table(episode_meta: Dict, outcome: Dict) -> str:
    rows = []
    for key in ("episode_id", "site_id", "site_domain", "sector", "goal", "revisit_index", "device_context", "operator", "paired_episode_id"):
        rows.append(f"<tr><td>{escape(key)}</td><td>{escape(str(episode_meta.get(key)))}</td></tr>")
    goal_achieved = outcome.get("goal_achieved")
    # goal_achieved is set only via the recording overlay's "Mark goal
    # achieved"/"Abandon" buttons -- a deliberate human judgment call, by
    # design (see recorder/interactive_v2.py) -- so None is a real,
    # expected state (operator never clicked either), not a bug to hide;
    # it just shouldn't render as a bare, unexplained Python "None".
    goal_achieved_display = "not recorded (operator didn't mark achieved/abandoned)" if goal_achieved is None else str(goal_achieved)
    rows.append(f"<tr><td>goal_achieved</td><td>{escape(goal_achieved_display)}</td></tr>")
    rows.append(f"<tr><td>steps_to_complete</td><td>{escape(str(outcome.get('steps_to_complete')))}</td></tr>")
    return f'<table class="meta-table">{"".join(rows)}</table>'


def _bbox_style(box: Dict, image_width: Optional[int], image_height: Optional[int]) -> str:
    if not image_width or not image_height:
        return "display:none;"
    x, y, w, h = box["x"], box["y"], box["width"], box["height"]
    return (
        f"left:{x / image_width * 100:.3f}%; top:{y / image_height * 100:.3f}%; "
        f"width:{w / image_width * 100:.3f}%; height:{h / image_height * 100:.3f}%;"
    )


def _render_step(step: Dict) -> str:
    if step["screenshot_b64"]:
        overlays = "".join(
            f'<div class="bbox {escape(box["verdict"])}" '
            f'style="{_bbox_style(box["bounding_box"], step["image_width"], step["image_height"])}" '
            f'title="{escape(chr(10).join(box["labels"]))}"></div>'
            for box in step["boxes"]
        )
        image_html = (
            f'<div class="screenshot-wrap">'
            f'<img src="data:image/png;base64,{step["screenshot_b64"]}" alt="step {step["step_id"]} screenshot">'
            f"{overlays}</div>"
        )
    else:
        error_note = f'<p class="capture-error">capture_error: {escape(step["capture_error"])}</p>' if step["capture_error"] else "<p>(no screenshot)</p>"
        image_html = error_note

    meta = f"{escape(str(step['action_type']))}"
    if step["selector"]:
        meta += f" &middot; <code>{escape(step['selector'])}</code>"
    if step["page_url_redacted"]:
        meta += f'<br>{escape(step["page_url_redacted"])}'

    return (
        f'<div class="filmstrip-step" id="step-{step["step_id"]}">'
        f'<h3>Step {step["step_id"]}</h3>{image_html}'
        f'<div class="step-meta">{meta}</div></div>'
    )


def _cell(value) -> str:
    if isinstance(value, (dict, list)):
        return escape(json.dumps(value))
    return escape(str(value))


def _render_generic_table(rows: List[Dict]) -> str:
    if not rows:
        return '<p class="section-empty">(none)</p>'
    columns = sorted({key for row in rows for key in row.keys()})
    header = "".join(f"<th>{escape(c)}</th>" for c in columns)
    body_rows = "".join(
        "<tr>" + "".join(f"<td>{_cell(row.get(c))}</td>" for c in columns) + "</tr>" for row in rows
    )
    return f'<table class="evidence-table"><tr>{header}</tr>{body_rows}</table>'


_EVIDENCE_SECTIONS = [
    ("Friction Metrics", "friction_metrics", "dict"),
    ("Visual Asymmetry Pairs", "visual_asymmetry", "list"),
    ("Claims", "claim_extraction", "list"),
    ("Price Drift", "price_drift", "dict"),
    ("Path Deviation", "path_deviation", "list"),
    ("Stated vs Actual", "stated_vs_actual", "list"),
]


def _render_evidence(evidence: Dict) -> str:
    if not evidence:
        return '<p class="section-empty">No evidence extracted yet -- run extract-evidence.</p>'
    sections = []
    for title, key, shape in _EVIDENCE_SECTIONS:
        value = evidence.get(key)
        rows = ([value] if value else []) if shape == "dict" else (value or [])
        sections.append(f"<h3>{escape(title)}</h3>{_render_generic_table(rows)}")

    complexity = evidence.get("complexity_metrics") or {}
    complexity_rows = []
    if complexity:
        complexity_rows.append({
            "total_actions_required": complexity.get("total_actions_required"),
            "option_counts": complexity.get("option_counts"),
            "copy_readability": complexity.get("copy_readability"),
        })
    sections.append(f"<h3>Complexity Metrics</h3>{_render_generic_table(complexity_rows)}")
    return "".join(sections)


def _render_pointer(pointer: Dict) -> str:
    label = f"signal: <code>{escape(pointer['signal'])}</code>"
    if pointer["selector"]:
        label += f" &middot; <code>{escape(pointer['selector'])}</code>"
    if pointer["step_id"] is not None:
        return f'<li><a href="#step-{pointer["step_id"]}">Step {pointer["step_id"]}</a> &middot; {label}</li>'
    return f"<li>(group-level evidence, no single step) &middot; {label}</li>"


def _render_attribute_section(section: Dict) -> str:
    pointers_html = (
        f'<ul class="pointer-list">{"".join(_render_pointer(p) for p in section["resolved_pointers"])}</ul>'
        if section["resolved_pointers"] else '<p class="section-empty">(no evidence pointers)</p>'
    )
    return (
        f'<div class="attribute-card">'
        f'<h3>{escape(section["attribute"])} {_badge(section)}</h3>'
        f'<div>agent: {escape(section["agent_version"])} ({escape(section["agent_type"])})</div>'
        f'<p class="reasoning">{escape(section["reasoning"])}</p>'
        f"{pointers_html}</div>"
    )


def _location_html(location: Dict) -> str:
    """{'step_id', 'selector', ...} -> where to look: the selector as
    code, linked to the exact filmstrip step if we have one (the
    filmstrip already draws a box on this exact element -- see
    journey/report_builder.py's _boxes_by_step). Honest, not invented,
    when a signal has neither (e.g. a friction-ratio measurement with no
    single element)."""
    parts = []
    if location.get("selector"):
        parts.append(f'<code>{escape(location["selector"])}</code>')
    if location.get("step_id") is not None:
        parts.append(f'<a href="#step-{location["step_id"]}">step {location["step_id"]}</a>')
    if not parts:
        return '<span class="no-element">(page/flow-level signal, no specific element)</span>'
    return " &middot; ".join(parts)


def _render_shared_element(shared: Dict) -> str:
    attrs = ", ".join(f"<code>{escape(a)}</code>" for a in shared["attributes"])
    return (
        f'<div class="shared-element">'
        f"<strong>Multiple patterns on the same element:</strong> {attrs}<br>"
        f"{_location_html(shared)}"
        f"</div>"
    )


def _region_thumbnail(region: Dict, filmstrip_by_step: Dict[int, Dict]) -> str:
    step_id = region.get("representative_step_id")
    step = filmstrip_by_step.get(step_id) if step_id is not None else None
    if not step or not step["screenshot_b64"]:
        return '<div class="region-thumb-empty">(no element)</div>'
    bbox = region.get("representative_bounding_box")
    overlay = ""
    if bbox and step["image_width"] and step["image_height"]:
        overlay = f'<div class="bbox fires" style="{_bbox_style(bbox, step["image_width"], step["image_height"])}"></div>'
    return (
        f'<div class="region-thumb"><div class="screenshot-wrap">'
        f'<img src="data:image/png;base64,{step["screenshot_b64"]}" alt="{escape(region["ui_region"])} thumbnail">'
        f"{overlay}</div></div>"
    )


def _render_region_card(region: Dict, filmstrip_by_step: Dict[int, Dict]) -> str:
    shared_html = "".join(_render_shared_element(s) for s in region["shared_elements"])
    shared_attrs = {a for s in region["shared_elements"] for a in s["attributes"]}

    remaining_fired = [a for a in region["attributes_fired"] if a["attribute"] not in shared_attrs]
    fired_html = "".join(
        f'<div class="fired-attr"><code>{escape(a["attribute"])}</code> fired &middot; {_location_html(a)}</div>'
        for a in remaining_fired
    )
    if not shared_html and not fired_html:
        fired_html = '<p class="section-empty">(nothing fired here)</p>'

    unsure_html = "".join(
        f'<div class="unsure-attr"><code>{escape(a["attribute"])}</code> unsure &middot; {_location_html(a)}</div>'
        for a in region["attributes_unsure"]
    )

    pattern = region["likely_pattern"]
    pattern_html = (
        f'<p class="likely-pattern">Likely pattern: <strong>{escape(pattern["name"])}</strong> '
        f'(source: {escape(pattern["source"])})</p>'
        if pattern else '<p class="section-empty">No likely_pattern.</p>'
    )
    return (
        f'<div class="region-card">'
        f'<h3>{escape(region["ui_region"])} '
        f'<span class="badge strength-{escape(region["finding_strength"])}">{escape(region["finding_strength"])}</span></h3>'
        f'{_region_thumbnail(region, filmstrip_by_step)}'
        f'<div class="region-body">{shared_html}{fired_html}{unsure_html}{pattern_html}'
        f'<p class="assessment">{escape(region["assessment"])}</p>'
        f"</div></div>"
    )


def _render_coverage_list(names: List[str], reasoning_by_attribute: Dict[str, str]) -> str:
    """Each attribute in this coverage bucket alongside the actual reason
    it landed there -- so "not assessable" reads as "checked for this,
    specifically didn't find it" rather than "skipped"."""
    if not names:
        return "—"
    items = []
    for name in names:
        reasoning = reasoning_by_attribute.get(name)
        if reasoning:
            items.append(f"<li><strong>{escape(name)}</strong> — {escape(reasoning)}</li>")
        else:
            items.append(f"<li><strong>{escape(name)}</strong></li>")
    return f'<ul class="coverage-list">{"".join(items)}</ul>'


_URGENCY_CLAIM_TEXT_MAX_CHARS = 160


def _shorten(text: str, max_chars: int) -> str:
    """For DISPLAY only -- a long text node (e.g. a whole marketing
    paragraph the urgency regex happened to match a phrase inside of)
    would otherwise swamp the card; the full text is always still in the
    underlying computed_output JSON, and available here via the title
    tooltip."""
    return text if len(text) <= max_chars else text[: max_chars - 1].rstrip() + "…"


def _render_urgency_claim(claim: Dict) -> str:
    steps = ", ".join(f'<a href="#step-{s}">{s}</a>' for s in claim["step_ids"]) or "—"
    location = f' &middot; <code>{escape(claim["selector"])}</code>' if claim["selector"] else ""
    full_text = claim["claim_text"] or claim["claim_type"]
    shown_text = _shorten(full_text, _URGENCY_CLAIM_TEXT_MAX_CHARS)
    title_attr = f' title="{escape(full_text)}"' if shown_text != full_text else ""
    return (
        f'<li><strong{title_attr}>{escape(shown_text)}</strong> '
        f"({escape(claim['claim_type'])}){location}<br>"
        f"seen at steps: {steps}</li>"
    )


def _render_urgency_claims(claims: List[Dict]) -> str:
    if not claims:
        return ""
    items = "".join(_render_urgency_claim(c) for c in claims)
    return (
        f'<div class="urgency-flag">'
        f"<strong>Urgency/countdown claims found — flagged for human review</strong> "
        f"(no attribute agent judges these automatically; check whether they're static/fake "
        f"or a genuine time-limited offer)"
        f'<ul class="coverage-list">{items}</ul>'
        f"</div>"
    )


def _render_overall(overall: Optional[Dict], reasoning_by_attribute: Dict[str, str]) -> str:
    if not overall:
        return '<p class="section-empty">No computed output yet -- run build-output.</p>'
    coverage = overall["coverage"]
    rs = overall["regions_summary"]
    flags = []
    if overall["coverage_limited"]:
        flags.append("coverage limited")
    if overall["human_review_recommended"]:
        flags.append("human review recommended")
    flags_html = f" &middot; {' &middot; '.join(flags)}" if flags else ""
    return (
        f'<div class="overall-banner verdict-{escape(overall["verdict"])}">'
        f'<div><strong>{escape(overall["verdict"])}</strong>{flags_html}</div>'
        f'<p>{escape(overall["summary"])}</p>'
        f'{_render_urgency_claims(overall["urgency_claims"])}'
        f'<table class="meta-table">'
        f'<tr><td>regions examined</td><td>{rs["total_regions_examined"]}</td></tr>'
        f'<tr><td>regions with findings</td><td>{rs["regions_with_findings"]}</td></tr>'
        f'<tr><td>regions clean</td><td>{rs["regions_clean"]}</td></tr>'
        f'<tr><td>assessed</td><td>{_render_coverage_list(coverage["assessed"], reasoning_by_attribute)}</td></tr>'
        f'<tr><td>checked — insufficient evidence</td>'
        f'<td>{_render_coverage_list(coverage["not_assessable"], reasoning_by_attribute)}</td></tr>'
        f'<tr><td>not assessed — pending Stage 2</td>'
        f'<td>{_render_coverage_list(coverage["stubbed_pending_stage2"], reasoning_by_attribute)}</td></tr>'
        f"</table></div>"
    )


def _render_mechanism_entry(entry: Dict) -> str:
    raw = json.dumps(entry["raw_response"], indent=2)
    attribute = entry["attribute"] or "(whole episode)"
    return (
        f'<div class="mechanism-entry">'
        f"<h3>{escape(entry['role'])} &middot; {escape(str(attribute))}</h3>"
        f"<div>model: {escape(entry['model_name'])} &middot; prompt_version: {escape(entry['prompt_version'])} "
        f"&middot; ingested_at: {escape(entry['ingested_at'])} &middot; operator: {escape(entry['operator'])}</div>"
        f"<pre>{escape(raw)}</pre></div>"
    )


def render_html(data: Dict) -> str:
    episode_meta = data["episode"]
    title = f"Dark Pattern Audit — {episode_meta.get('episode_id')}"

    filmstrip_by_step = {s["step_id"]: s for s in data["filmstrip"]}
    regions_html = "".join(_render_region_card(r, filmstrip_by_step) for r in data["regions"]) or (
        '<p class="section-empty">No regions with findings -- either build-output has not run yet, '
        "or this episode is clean.</p>"
    )
    filmstrip_html = "".join(_render_step(s) for s in data["filmstrip"]) or '<p class="section-empty">(no steps)</p>'
    attributes_html = "".join(_render_attribute_section(s) for s in data["attribute_sections"]) or '<p class="section-empty">No attribute results yet -- run run-attributes.</p>'
    mechanism_html = "".join(_render_mechanism_entry(e) for e in data["mechanism_verdict_entries"]) or '<p class="section-empty">No manually-ingested LLM verdicts yet -- run build-payload / ingest-response.</p>'
    reasoning_by_attribute = {s["attribute"]: s["reasoning"] for s in data["attribute_sections"]}

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{escape(title)}</title>
<style>{_CSS}</style>
</head>
<body>
<h1>{escape(title)}</h1>
{_meta_table(episode_meta, data["outcome"])}

<h2>Findings</h2>
{regions_html}

<h2>Coverage</h2>
{_render_overall(data["overall"], reasoning_by_attribute)}

<h2>All Verdicts</h2>
{attributes_html}

<h2>Journey</h2>
<div class="filmstrip">{filmstrip_html}</div>

<h2>Mechanism Verdict (Stage 2, manually ingested)</h2>
{mechanism_html}

<h2>Evidence</h2>
{_render_evidence(data["evidence"])}

</body>
</html>
"""


def _render_verdict_counts(counts: Dict[str, int]) -> str:
    if not counts:
        return "(no attributes run)"
    return " &middot; ".join(f"{escape(v)}: {n}" for v, n in sorted(counts.items()))


def _render_fires_list(attributes: List[str]) -> str:
    if not attributes:
        return "—"
    return '<span class="fires-list">' + "".join(f"<span>{escape(a)}</span>" for a in attributes) + "</span>"


def _render_episode_row(episode: Dict, report_link: Optional[str]) -> str:
    link = f'<a href="{escape(report_link)}">{escape(episode["episode_id"])}</a>' if report_link else escape(episode["episode_id"])
    return (
        "<tr>"
        f"<td>{link}</td>"
        f"<td>{escape(str(episode['goal']))}</td>"
        f"<td>{escape(str(episode['revisit_index']))}</td>"
        f"<td>{escape(str(episode['site_domain']))}</td>"
        f"<td>{escape(str(episode['device_context']))}</td>"
        f"<td>{escape(str(episode['operator']))}</td>"
        f"<td>{_render_verdict_counts(episode['verdict_counts'])}</td>"
        f"<td>{_render_fires_list(episode['firing_attributes'])}</td>"
        "</tr>"
    )


def _render_goal_section(goal: Optional[str], episodes: List[Dict], report_links: Dict[str, str]) -> str:
    header = ("Goal: " + escape(str(goal))) if goal else "No goal recorded"
    rows = "".join(_render_episode_row(e, report_links.get(e["episode_id"])) for e in episodes)
    table = (
        '<table class="episode-table"><tr>'
        "<th>episode_id</th><th>goal</th><th>revisit</th><th>site_domain</th>"
        "<th>device</th><th>operator</th><th>verdict counts</th><th>fired</th>"
        f"</tr>{rows}</table>"
    )
    return f"<h3>{header}</h3>{table}"


def _render_group_evidence_summary(group_evidence: Dict) -> str:
    claim_rows = _render_generic_table(group_evidence.get("claim_persistence") or [])
    timer_rows = _render_generic_table(group_evidence.get("timer_reset_detection") or [])
    paired_rows = _render_generic_table(group_evidence.get("paired_flow_comparison") or [])
    return (
        f"<h3>group_id: {escape(group_evidence.get('group_id', ''))} "
        f"(goal: {escape(str(group_evidence.get('goal')))})</h3>"
        f"<h4>claim_persistence</h4>{claim_rows}"
        f"<h4>timer_reset_detection</h4>{timer_rows}"
        f"<h4>paired_flow_comparison</h4>{paired_rows}"
    )


def render_site_html(data: Dict, report_links: Dict[str, str]) -> str:
    """report_links: episode_id -> path to that episode's own report.html,
    relative to where THIS rollup page will be written (report_site.py
    computes these via os.path.relpath before calling this)."""
    title = f"Dark Pattern Audit — site rollup — {data['site_id']}"

    episodes_by_goal: Dict[Optional[str], List[Dict]] = {}
    for e in data["episodes"]:
        episodes_by_goal.setdefault(e["goal"], []).append(e)

    goal_sections = "".join(
        _render_goal_section(goal, episodes_by_goal[goal], report_links)
        for goal in [*data["goals"], *([None] if None in episodes_by_goal else [])]
    )
    if not data["episodes"]:
        goal_sections = '<p class="section-empty">No recorded episodes found for this site_id.</p>'

    group_evidence_html = "".join(_render_group_evidence_summary(g) for g in data["group_evidence_summaries"])
    if not group_evidence_html:
        group_evidence_html = '<p class="section-empty">No group evidence computed yet -- run extract-group-evidence.</p>'

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{escape(title)}</title>
<style>{_CSS}</style>
</head>
<body>
<h1>{escape(title)}</h1>
<p>{len(data["episodes"])} episode(s) across {len(data["goals"])} goal(s).</p>

<h2>Episodes by Goal</h2>
{goal_sections}

<h2>Cross-Episode Signals (claim_persistence / timer_reset_detection / paired_flow_comparison)</h2>
{group_evidence_html}

</body>
</html>
"""
