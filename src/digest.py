"""Generates the HTML digest pages.

The page is split in two by src/routing.py: qualified assignments first, then
everything else under "Osäkra / anställningar" with a short reason label.
All scraped text is HTML-escaped before it is interpolated into the markup.
"""

import os
from datetime import date
from html import escape

from src.models import Assignment
from src.routing import disqualify_reason, is_qualified

DOCS_DIR = "docs"
ARCHIVE_DIR = os.path.join(DOCS_DIR, "archive")


def _sort_key(a: Assignment):
    """Highest score first; new assignments win ties."""
    return (-a.relevance_score, 0 if a.is_new else 1)


def _split(assignments: list[Assignment]) -> tuple[list[Assignment], list[Assignment]]:
    qualified = sorted((a for a in assignments if is_qualified(a)), key=_sort_key)
    other = sorted((a for a in assignments if not is_qualified(a)), key=_sort_key)
    return qualified, other


def generate(assignments: list[Assignment], run_date: str | None = None, warning: str = "") -> None:
    """Write docs/index.html (latest) and docs/archive/YYYY-MM-DD.html."""
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    today = run_date or date.today().isoformat()
    qualified, other = _split(assignments)
    new_count = sum(1 for a in qualified if a.is_new)

    html = _build_html(qualified, other, today, new_count, warning)

    archive_path = os.path.join(ARCHIVE_DIR, f"{today}.html")
    index_path = os.path.join(DOCS_DIR, "index.html")

    with open(archive_path, "w", encoding="utf-8") as f:
        f.write(html)
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(
        f"[digest] Wrote {index_path} and {archive_path} "
        f"({len(qualified)} uppdrag, {len(other)} osäkra, {new_count} nya kvalificerade)"
    )


def _new_today_strip(qualified: list[Assignment]) -> str:
    """Compact list of qualified new-today assignments shown above the grid."""
    new_ones = [a for a in qualified if a.is_new]
    if not new_ones:
        return ""
    items = "\n".join(
        f'    <li><a href="{escape(a.url, quote=True)}" target="_blank" rel="noopener">'
        f'{escape(a.title)}</a>'
        f' <span class="strip-score {_score_class(a.relevance_score)}">{_score_text(a.relevance_score)}</span>'
        f' <span class="strip-src">{escape(a.source)}</span></li>'
        for a in new_ones
    )
    return f"""<div class="new-strip">
  <div class="new-strip-header">&#x2728; New today ({len(new_ones)})</div>
  <ul class="new-strip-list">
{items}
  </ul>
</div>"""


def _section(title: str, subtitle: str, assignments: list[Assignment], empty_text: str,
             section_class: str = "") -> str:
    cards = "\n".join(_card(a) for a in assignments) if assignments else (
        f'<p class="empty">{escape(empty_text)}</p>'
    )
    wrapper_class = f"section {section_class}".strip()
    subtitle_html = (
        f'<span class="section-sub">{escape(subtitle)}</span>' if subtitle else ""
    )
    return f"""<section class="{wrapper_class}">
  <div class="section-head">
    <h2>{escape(title)}</h2>
    <span class="section-count">{len(assignments)}</span>
    {subtitle_html}
  </div>
  <div class="grid">
    {cards}
  </div>
</section>"""


def _build_html(qualified: list[Assignment], other: list[Assignment], today: str,
                new_count: int, warning: str = "") -> str:
    sources = sorted({a.source for a in qualified + other})
    source_tags = " ".join(f'<span class="source-tag">{escape(s)}</span>' for s in sources)
    new_strip = _new_today_strip(qualified)
    warning_banner = (
        f'<div class="warning-banner">&#x26A0;&#xFE0F; {escape(warning)}</div>' if warning else ""
    )

    main_section = _section(
        "Uppdrag",
        "konsultuppdrag som matchar profilen",
        qualified,
        "Inga kvalificerade uppdrag idag.",
    )
    other_section = _section(
        "Osäkra / anställningar",
        "filtrerade bort från mailet",
        other,
        "Inget hamnade i den här kategorin idag.",
        section_class="section-muted",
    )

    return f"""<!DOCTYPE html>
<html lang="sv">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Contract Assignments – {today}</title>
<style>
  :root {{
    --bg: #0f1117;
    --surface: #1a1d27;
    --border: #2a2d3e;
    --accent: #7c6af7;
    --accent2: #4fc3f7;
    --new: #43d68c;
    --text: #e2e4f0;
    --muted: #8b8fa8;
    --score-high: #43d68c;
    --score-mid: #ffd740;
    --score-low: #ff6b6b;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; font-size: 15px; line-height: 1.6; }}
  header {{ background: var(--surface); border-bottom: 1px solid var(--border); padding: 20px 32px; display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }}
  header h1 {{ font-size: 1.3rem; font-weight: 700; color: var(--accent); }}
  header .meta {{ color: var(--muted); font-size: 0.85rem; }}
  .badge {{ background: var(--accent); color: #fff; border-radius: 999px; padding: 2px 10px; font-size: 0.78rem; font-weight: 600; }}
  .badge.new {{ background: var(--new); color: #0f1117; }}
  .badge.muted {{ background: var(--border); color: var(--muted); }}
  main {{ max-width: 980px; margin: 0 auto; padding: 24px 16px; }}
  .toolbar {{ display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 20px; align-items: center; }}
  .source-tag {{ background: var(--border); color: var(--muted); border-radius: 6px; padding: 3px 10px; font-size: 0.78rem; }}
  .new-strip {{ background: rgba(67,214,140,0.07); border: 1px solid rgba(67,214,140,0.3); border-radius: 12px; padding: 14px 18px; margin-bottom: 24px; }}
  .new-strip-header {{ color: var(--new); font-size: 0.82rem; font-weight: 700; letter-spacing: 0.04em; margin-bottom: 8px; }}
  .new-strip-list {{ list-style: none; display: flex; flex-direction: column; gap: 5px; }}
  .new-strip-list li {{ font-size: 0.88rem; }}
  .new-strip-list a {{ color: var(--text); text-decoration: none; }}
  .new-strip-list a:hover {{ color: var(--accent2); }}
  .strip-score {{ font-size: 0.72rem; font-weight: 700; border-radius: 4px; padding: 1px 5px; margin-left: 6px; vertical-align: middle; }}
  .strip-src {{ color: var(--muted); font-size: 0.75rem; margin-left: 6px; }}
  .section {{ margin-bottom: 36px; }}
  .section-head {{ display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; margin-bottom: 14px; padding-bottom: 8px; border-bottom: 1px solid var(--border); }}
  .section-head h2 {{ font-size: 1.05rem; font-weight: 700; color: var(--text); }}
  .section-count {{ background: var(--border); color: var(--muted); border-radius: 999px; padding: 1px 9px; font-size: 0.75rem; font-weight: 700; }}
  .section-sub {{ color: var(--muted); font-size: 0.8rem; }}
  .section-muted {{ border-top: 1px dashed var(--border); padding-top: 24px; }}
  .section-muted .section-head h2 {{ color: var(--muted); }}
  .section-muted .card {{ opacity: 0.72; }}
  .section-muted .card:hover {{ opacity: 1; }}
  .grid {{ display: grid; gap: 16px; }}
  .card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 18px 20px; transition: border-color 0.15s, opacity 0.15s; }}
  .card:hover {{ border-color: var(--accent); }}
  .card.is-new {{ border-left: 3px solid var(--new); background: rgba(67,214,140,0.04); }}
  .card-header {{ display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; margin-bottom: 8px; }}
  .card-title {{ font-size: 1rem; font-weight: 600; }}
  .card-title a {{ color: var(--text); text-decoration: none; }}
  .card-title a:hover {{ color: var(--accent2); }}
  .reason {{ background: rgba(139,143,168,0.15); color: var(--muted); border: 1px solid var(--border); border-radius: 999px; padding: 1px 9px; font-size: 0.72rem; font-weight: 600; vertical-align: middle; margin-left: 6px; white-space: nowrap; }}
  .score {{ font-size: 0.78rem; font-weight: 700; border-radius: 6px; padding: 2px 8px; white-space: nowrap; }}
  .score-high {{ background: rgba(67,214,140,0.15); color: var(--score-high); }}
  .score-mid {{ background: rgba(255,215,64,0.15); color: var(--score-mid); }}
  .score-low {{ background: rgba(255,107,107,0.15); color: var(--score-low); }}
  .score-none {{ background: rgba(139,143,168,0.15); color: var(--muted); }}
  .warning-banner {{ background: rgba(255,215,64,0.1); border: 1px solid rgba(255,215,64,0.4); color: var(--score-mid); border-radius: 12px; padding: 12px 18px; margin-bottom: 20px; font-size: 0.88rem; }}
  .card-meta {{ color: var(--muted); font-size: 0.82rem; margin-bottom: 8px; display: flex; flex-wrap: wrap; gap: 10px; }}
  .card-meta span::before {{ content: ''; }}
  .card-summary {{ font-size: 0.88rem; color: #bbbdd6; margin-top: 6px; }}
  .new-pill {{ background: var(--new); color: #0f1117; border-radius: 999px; padding: 1px 8px; font-size: 0.72rem; font-weight: 700; vertical-align: middle; margin-left: 6px; }}
  .empty {{ color: var(--muted); text-align: center; padding: 40px 0; }}
  footer {{ text-align: center; color: var(--muted); font-size: 0.78rem; padding: 32px 16px; border-top: 1px solid var(--border); margin-top: 32px; }}
  @media (max-width: 600px) {{ header {{ padding: 14px 16px; }} }}
</style>
</head>
<body>
<header>
  <h1>&#x1F4CB; Contract Assignments</h1>
  <span class="meta">Stockholm · Data Engineering / BI / Analytics</span>
  <span class="badge">{len(qualified)} uppdrag</span>
  <span class="badge muted">{len(other)} osäkra</span>
  {'<span class="badge new">' + str(new_count) + ' nya</span>' if new_count else ''}
  <span class="meta" style="margin-left:auto">{today}</span>
</header>
<main>
  <div class="toolbar">
    <span style="color:var(--muted);font-size:0.82rem">Sources:</span>
    {source_tags}
    <a href="archive/" style="margin-left:auto;color:var(--muted);font-size:0.82rem;text-decoration:none">&#x1F4C1; Archive</a>
  </div>
  {warning_banner}
  {new_strip}
  {main_section}
  {other_section}
</main>
<footer>Generated {today} · <a href="https://github.com" style="color:var(--muted)">NI-Contracts</a></footer>
</body>
</html>"""


def _score_class(score: int) -> str:
    if score >= 7:
        return "score-high"
    if score >= 4:
        return "score-mid"
    if score >= 1:
        return "score-low"
    return "score-none"


def _score_text(score: int) -> str:
    return f"{score}/10" if score else "–"


def _card(a: Assignment) -> str:
    new_pill = '<span class="new-pill">NEW</span>' if a.is_new else ""
    reason = disqualify_reason(a)
    reason_badge = f'<span class="reason">{escape(reason)}</span>' if reason else ""
    tooltip = "" if a.relevance_score else ' title="Ej poängsatt"'
    score_label = (
        f'<span class="score {_score_class(a.relevance_score)}"{tooltip}>'
        f'{_score_text(a.relevance_score)}</span>'
    )
    summary = a.summary or ""
    summary_block = f'<div class="card-summary">{escape(summary)}</div>' if summary else ""
    card_class = "card is-new" if a.is_new else "card"

    return f"""<div class="{card_class}">
  <div class="card-header">
    <div class="card-title"><a href="{escape(a.url, quote=True)}" target="_blank" rel="noopener">{escape(a.title)}</a>{new_pill}{reason_badge}</div>
    {score_label}
  </div>
  <div class="card-meta">
    <span>🏢 {escape(a.company)}</span>
    <span>📍 {escape(a.location)}</span>
    <span>🔗 {escape(a.source)}</span>
    <span>🗓 {escape(a.date_found)}</span>
  </div>
  {summary_block}
</div>"""
