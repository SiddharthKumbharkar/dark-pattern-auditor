"""Renders journey/report_summary_builder.py's plain-language data into
two self-contained, presentation-grade HTML views:
  - render_summary_html(): one episode, full page (report_summary.html).
  - render_compare_html(): two episodes side by side (report_compare.html),
    the ON/OFF demo artifact.

Same conventions as journey/report_html.py (the technical report this
module deliberately does not touch or import from): plain string
building, no templating engine, no external assets, every piece of
episode-derived text passed through html.escape() before insertion. The
two renderers never show a raw CSS selector, JSON blob, attribute code
(outside a parenthetical next to its own plain-English label), or a bare
severity number -- see journey/report_summary_builder.py's docstring for
where that translation actually happens; this module only lays out
already-plain-language data.
"""

from html import escape
from typing import Dict, List, Optional

_CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; margin: 0; padding: 0;
       background: #fafafa; color: #14161a; line-height: 1.55; }
@media (prefers-color-scheme: dark) { body { background: #111318; color: #f0f0f0; } }
.page { max-width: 1000px; margin: 0 auto; padding: 2.5rem 2rem 4rem; }

h1, h2, h3 { font-weight: 700; }
h2 { font-size: 1.5rem; margin: 0 0 1.1rem; }

.banner { border-radius: 16px; padding: 2.2rem 2.4rem; margin-bottom: 2.5rem; }
.banner.clean   { background: #e9f9f0; border: 2px solid #1f9d5c; }
.banner.warn    { background: #fff8e6; border: 2px solid #c98a12; }
.banner.danger  { background: #fdecec; border: 2px solid #d1373f; }
@media (prefers-color-scheme: dark) {
  .banner.clean  { background: #0d2a1c; border-color: #2fbf71; }
  .banner.warn   { background: #2c2109; border-color: #e2a63c; }
  .banner.danger { background: #2c1112; border-color: #f0555d; }
}
.banner h1 { margin: 0 0 0.6rem; font-size: 2.1rem; }
.banner.clean h1  { color: #1a7a48; }
.banner.warn h1   { color: #a5700e; }
.banner.danger h1 { color: #b32e35; }
@media (prefers-color-scheme: dark) {
  .banner.clean h1  { color: #4fe093; }
  .banner.warn h1   { color: #f0bf5c; }
  .banner.danger h1 { color: #f57b81; }
}
.banner p.plain { font-size: 1.2rem; margin: 0.3rem 0 1.1rem; max-width: 46rem; }
.meta-line { font-size: 0.95rem; opacity: 0.7; }
.meta-line span + span::before { content: " · "; }

.section { margin: 2.8rem 0; }

.finding-card { border: 1px solid #dcdcdc; border-radius: 14px; padding: 1.5rem 1.7rem; margin-bottom: 1.3rem; background: #fff; }
@media (prefers-color-scheme: dark) { .finding-card { background: #1a1d24; border-color: #33363f; } }
.finding-card h3 { margin: 0 0 0.6rem; font-size: 1.25rem; }
.finding-card p.description { margin: 0.2rem 0 1rem; font-size: 1.02rem; }
.mechanism-chip { display: inline-block; background: #eef1f5; border-radius: 999px; padding: 0.3rem 0.9rem;
  margin: 0.15rem 0.35rem 0.15rem 0; font-size: 0.88rem; }
@media (prefers-color-scheme: dark) { .mechanism-chip { background: #262a33; } }

.empty-note { font-size: 1.02rem; opacity: 0.8; padding: 0.5rem 0; }

.filmstrip { display: flex; flex-wrap: wrap; gap: 1.5rem; }
.step-card { width: 260px; border-radius: 12px; overflow: hidden; border: 3px solid transparent; background: #fff;
  box-shadow: 0 1px 3px #0002; }
@media (prefers-color-scheme: dark) { .step-card { background: #1a1d24; box-shadow: none; border-color: #2a2d35; } }
.step-card.flag-fires  { border-color: #d1373f; }
.step-card.flag-unsure { border-color: #c98a12; }
.step-card img { display: block; width: 100%; height: auto; }
.step-card .step-body { padding: 0.7rem 0.9rem 0.9rem; }
.step-card .step-num { font-weight: 700; font-size: 0.95rem; }
.flag-tag { display: inline-block; font-size: 0.68rem; font-weight: 700; text-transform: uppercase;
  letter-spacing: 0.04em; border-radius: 999px; padding: 0.15rem 0.55rem; margin-left: 0.5rem; vertical-align: middle; }
.flag-tag.flag-fires  { background: #fdecec; color: #b32e35; }
.flag-tag.flag-unsure { background: #fff8e6; color: #a5700e; }
@media (prefers-color-scheme: dark) {
  .flag-tag.flag-fires  { background: #2c1112; color: #f57b81; }
  .flag-tag.flag-unsure { background: #2c2109; color: #f0bf5c; }
}
.step-sentence { font-size: 0.9rem; margin: 0.5rem 0 0; }
.step-sentence + .step-sentence { margin-top: 0.3rem; }
.no-screenshot { padding: 2.5rem 0.5rem; text-align: center; opacity: 0.6; font-size: 0.85rem; }

.coverage-line { font-size: 1rem; opacity: 0.85; margin-top: 2.5rem; padding-top: 1.5rem; border-top: 1px solid #8883; }

.compare-header { text-align: center; margin-bottom: 2.5rem; }
.compare-header h1 { font-size: 1.9rem; margin: 0 0 0.3rem; }
.compare-header p { opacity: 0.7; margin: 0; }
.compare-wrap { display: flex; gap: 2rem; flex-wrap: wrap; align-items: flex-start; }
.compare-col { flex: 1 1 440px; min-width: 340px; }
.compare-col .col-title { text-align: center; font-size: 1.05rem; font-weight: 700; margin: 0 0 1rem;
  opacity: 0.75; overflow-wrap: break-word; padding: 0 0.5rem; }
.compare-col .banner { margin-bottom: 1.8rem; }
.compare-col .banner h1 { font-size: 1.6rem; }
.compare-col .banner p.plain { font-size: 1.02rem; }
.compare-col .finding-card { padding: 1.1rem 1.3rem; }
.compare-col .step-card { width: 150px; }
.compare-col .filmstrip { gap: 0.9rem; }
"""


def _meta_line(meta: Dict) -> str:
    parts = []
    if meta.get("site"):
        parts.append(f"<span>{escape(str(meta['site']))}</span>")
    if meta.get("goal_label"):
        parts.append(f"<span>{escape(meta['goal_label'])}</span>")
    if meta.get("date"):
        parts.append(f"<span>{escape(meta['date'])}</span>")
    if meta.get("goal_achieved_label"):
        parts.append(f"<span>Goal {escape(meta['goal_achieved_label'].lower())}</span>")
    if not parts:
        return ""
    return f'<p class="meta-line">{"".join(parts)}</p>'


def _render_banner(banner: Dict, meta: Dict) -> str:
    return (
        f'<div class="banner {escape(banner["level"])}">'
        f'<h1>{escape(banner["heading"])}</h1>'
        f'<p class="plain">{escape(banner["plain_language"])}</p>'
        f"{_meta_line(meta)}"
        f"</div>"
    )


def _render_finding_card(finding: Dict) -> str:
    chips = "".join(f'<span class="mechanism-chip">{escape(m)}</span>' for m in finding["mechanisms"])
    return (
        f'<div class="finding-card">'
        f'<h3>{escape(finding["pattern_name"])}</h3>'
        f'<p class="description">{escape(finding["description"])}</p>'
        f"{chips}"
        f"</div>"
    )


def _render_findings_section(findings: List[Dict], empty_message: Optional[str]) -> str:
    if not findings:
        return f'<p class="empty-note">{escape(empty_message or "")}</p>'
    return "".join(_render_finding_card(f) for f in findings)


def _render_step_sentence(sentence: Dict) -> str:
    title_attr = f' title="{escape(" · ".join(sentence["selectors"]))}"' if sentence["selectors"] else ""
    return f'<p class="step-sentence"{title_attr}>{escape(sentence["text"])}</p>'


def _render_step_card(step: Dict) -> str:
    flag_class = f" flag-{step['flag_level']}" if step["flagged"] else ""
    if step["screenshot_b64"]:
        image_html = f'<img src="data:image/png;base64,{step["screenshot_b64"]}" alt="step {step["step_id"]} screenshot">'
    else:
        image_html = '<div class="no-screenshot">(no screenshot)</div>'

    tag_html = f'<span class="flag-tag flag-{step["flag_level"]}">flagged</span>' if step["flagged"] else ""
    sentences_html = "".join(_render_step_sentence(s) for s in step["sentences"])

    return (
        f'<div class="step-card{flag_class}">{image_html}'
        f'<div class="step-body"><span class="step-num">Step {step["step_id"]}</span>{tag_html}'
        f"{sentences_html}</div></div>"
    )


def _render_filmstrip(steps: List[Dict]) -> str:
    return "".join(_render_step_card(s) for s in steps) or '<p class="empty-note">(no steps recorded)</p>'


def render_summary_html(data: Dict) -> str:
    meta = data["meta"]
    title = f"Dark Pattern Audit — Summary — {meta.get('site') or meta.get('episode_id')}"

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<style>{_CSS}</style>
</head>
<body>
<div class="page">
{_render_banner(data["banner"], meta)}

<div class="section">
<h2>What was found</h2>
{_render_findings_section(data["findings"], data["findings_empty_message"])}
</div>

<div class="section">
<h2>The journey</h2>
<div class="filmstrip">{_render_filmstrip(data["steps"])}</div>
</div>

<p class="coverage-line">{escape(data["coverage_sentence"])}</p>
</div>
</body>
</html>
"""


def _render_compare_column(data: Dict, label: str) -> str:
    meta = data["meta"]
    return (
        f'<div class="compare-col">'
        f'<div class="col-title">{escape(label)}</div>'
        f'{_render_banner(data["banner"], meta)}'
        f'{_render_findings_section(data["findings"], data["findings_empty_message"])}'
        f'<div class="filmstrip">{_render_filmstrip(data["steps"])}</div>'
        f'<p class="coverage-line">{escape(data["coverage_sentence"])}</p>'
        f"</div>"
    )


def render_compare_html(left: Dict, right: Dict, left_label: str, right_label: str) -> str:
    left_site = left["meta"].get("site") or left["meta"].get("episode_id")
    right_site = right["meta"].get("site") or right["meta"].get("episode_id")
    title = f"Dark Pattern Audit — Comparison — {left_site} vs {right_site}"

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<style>{_CSS}</style>
</head>
<body>
<div class="page">
<div class="compare-header">
<h1>Same site, same flow — {escape(str(left_site))}</h1>
<p>Side-by-side comparison of the two recorded versions of this flow.</p>
</div>
<div class="compare-wrap">
{_render_compare_column(left, left_label)}
{_render_compare_column(right, right_label)}
</div>
</div>
</body>
</html>
"""
