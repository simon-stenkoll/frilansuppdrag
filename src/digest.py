"""Generates the HTML digest pages."""

import os
from datetime import date
from src.config import DIGEST_LOW_SCORE
from src.models import Assignment

DOCS_DIR = "docs"
ARCHIVE_DIR = os.path.join(DOCS_DIR, "archive")


def generate(
    assignments: list[Assignment],
    run_date: str | None = None,
    warning: str = "",
    funnel_note: str = "",
) -> None:
    """Write docs/index.html (latest) and docs/archive/YYYY-MM-DD.html."""
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    today = run_date or date.today().isoformat()
    new_count = sum(1 for a in assignments if a.is_new)

    html = _build_html(assignments, today, new_count, warning, funnel_note)

    archive_path = os.path.join(ARCHIVE_DIR, f"{today}.html")
    index_path = os.path.join(DOCS_DIR, "index.html")

    with open(archive_path, "w", encoding="utf-8") as f:
        f.write(html)
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"[digest] Wrote {index_path} and {archive_path} ({len(assignments)} assignments, {new_count} new)")


def _new_today_strip(assignments: list[Assignment]) -> str:
    """Compact list of new-today assignments shown above the ranked grid."""
    new_ones = [a for a in assignments if a.is_new]
    if not new_ones:
        return ""
    items = "\n".join(
        f'    <li><a href="{a.url}" target="_blank" rel="noopener">{a.title}</a>'
        f' <span class="strip-score {_score_class(a.relevance_score)}">{_score_text(a.relevance_score)}</span>'
        f' <span class="strip-src">{a.source}</span></li>'
        for a in new_ones
    )
    return f"""<div class="new-strip">
  <div class="new-strip-header">&#x2728; New today ({len(new_ones)})</div>
  <ul class="new-strip-list">
{items}
  </ul>
</div>"""


def _build_html(
    assignments: list[Assignment],
    today: str,
    new_count: int,
    warning: str = "",
    funnel_note: str = "",
) -> str:
    # Scored-but-low assignments collapse at the bottom; unscored (0) stay in the grid.
    low = [a for a in assignments if 1 <= a.relevance_score <= DIGEST_LOW_SCORE]
    main_list = [a for a in assignments if not (1 <= a.relevance_score <= DIGEST_LOW_SCORE)]

    cards_html = "\n".join(_card(a) for a in main_list) if main_list else (
        '<p class="empty">No matching assignments found today.</p>'
    )
    low_section = ""
    if low:
        low_cards = "\n".join(_card(a) for a in low)
        low_section = f"""<details class="low-relevance">
    <summary>Låg relevans ({len(low)} uppdrag med poäng ≤ {DIGEST_LOW_SCORE})</summary>
    <div class="grid">
      {low_cards}
    </div>
  </details>"""

    sources = sorted({a.source for a in assignments})
    source_tags = " ".join(f'<span class="source-tag">{s}</span>' for s in sources)
    new_strip = _new_today_strip(assignments)
    warning_banner = f'<div class="warning-banner">&#x26A0;&#xFE0F; {warning}</div>' if warning else ""

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
  .grid {{ display: grid; gap: 16px; }}
  .card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 18px 20px; transition: border-color 0.15s; }}
  .card:hover {{ border-color: var(--accent); }}
  .card.is-new {{ border-left: 3px solid var(--new); background: rgba(67,214,140,0.04); }}
  .card-header {{ display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; margin-bottom: 8px; }}
  .card-title {{ font-size: 1rem; font-weight: 600; }}
  .card-title a {{ color: var(--text); text-decoration: none; }}
  .card-title a:hover {{ color: var(--accent2); }}
  .score {{ font-size: 0.78rem; font-weight: 700; border-radius: 6px; padding: 2px 8px; white-space: nowrap; }}
  .score-high {{ background: rgba(67,214,140,0.15); color: var(--score-high); }}
  .score-mid {{ background: rgba(255,215,64,0.15); color: var(--score-mid); }}
  .score-low {{ background: rgba(255,107,107,0.15); color: var(--score-low); }}
  .score-none {{ background: rgba(139,143,168,0.15); color: var(--muted); }}
  .warning-banner {{ background: rgba(255,215,64,0.1); border: 1px solid rgba(255,215,64,0.4); color: var(--score-mid); border-radius: 12px; padding: 12px 18px; margin-bottom: 20px; font-size: 0.88rem; }}
  .low-relevance {{ margin-top: 28px; }}
  .low-relevance summary {{ color: var(--muted); font-size: 0.88rem; cursor: pointer; padding: 10px 0; }}
  .low-relevance .grid {{ margin-top: 12px; opacity: 0.75; }}
  .card-meta {{ color: var(--muted); font-size: 0.82rem; margin-bottom: 8px; display: flex; flex-wrap: wrap; gap: 10px; }}
  .card-meta span::before {{ content: ''; }}
  .card-summary {{ font-size: 0.88rem; color: #bbbdd6; margin-top: 6px; }}
  .new-pill {{ background: var(--new); color: #0f1117; border-radius: 999px; padding: 1px 8px; font-size: 0.72rem; font-weight: 700; vertical-align: middle; margin-left: 6px; }}
  .empty {{ color: var(--muted); text-align: center; padding: 60px 0; }}
  footer {{ text-align: center; color: var(--muted); font-size: 0.78rem; padding: 32px 16px; border-top: 1px solid var(--border); margin-top: 32px; }}
  @media (max-width: 600px) {{ header {{ padding: 14px 16px; }} }}
</style>
</head>
<body>
<header>
  <h1>&#x1F4CB; Contract Assignments</h1>
  <span class="meta">Stockholm · Data Engineering / BI / Analytics</span>
  <span class="badge">{len(assignments)} results</span>
  {'<span class="badge new">' + str(new_count) + ' new</span>' if new_count else ''}
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
  <div class="grid">
    {cards_html}
  </div>
  {low_section}
</main>
<footer>Generated {today}{' · Filter: ' + funnel_note if funnel_note else ''} · <a href="https://github.com" style="color:var(--muted)">NI-Contracts</a></footer>
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
    tooltip = "" if a.relevance_score else ' title="Ej poängsatt"'
    score_label = (
        f'<span class="score {_score_class(a.relevance_score)}"{tooltip}>'
        f'{_score_text(a.relevance_score)}</span>'
    )
    summary_block = f'<div class="card-summary">{a.summary}</div>' if a.summary else ""
    card_class = "card is-new" if a.is_new else "card"

    return f"""<div class="{card_class}">
  <div class="card-header">
    <div class="card-title"><a href="{a.url}" target="_blank" rel="noopener">{a.title}</a>{new_pill}</div>
    {score_label}
  </div>
  <div class="card-meta">
    <span>🏢 {a.company}</span>
    <span>📍 {a.location}</span>
    <span>🔗 {a.source}</span>
    <span>🗓 {a.date_found}</span>
  </div>
  {summary_block}
</div>"""
