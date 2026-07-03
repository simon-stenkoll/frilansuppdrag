"""Main orchestrator — runs all scrapers, deduplicates, summarizes, generates digest."""

import asyncio
import os
import traceback
from src.scrapers import jobtech, ework, brainville, broker_portals, indeed, linkedin_google, verama
from src.dedup import deduplicate
from src.state import mark_new, check_source_health
from src.summarizer import summarize
from src.digest import generate
from src.notify import post_to_discord
from src.config import DISABLED_SCRAPERS, PAGE_URL_FALLBACK
from src.scrapers.utils import is_contract, FUNNEL_STATS

SCRAPERS = [
    ("Platsbanken (JobTech)", jobtech.scrape),
    ("Ework", ework.scrape),
    ("Ework (Verama)", verama.scrape),
    ("Brainville", brainville.scrape),
    ("Broker Portals", broker_portals.scrape),
    ("Indeed", indeed.scrape),
    ("LinkedIn (Google)", linkedin_google.scrape),
]


async def run_all_scrapers() -> tuple[list, dict[str, int]]:
    all_results = []
    counts: dict[str, int] = {}
    for name, scrape_fn in SCRAPERS:
        if name in DISABLED_SCRAPERS:
            print(f"[{name}] SKIPPED — temporarily disabled")
            continue
        try:
            results = await scrape_fn()
            print(f"[{name}] {len(results)} assignments found")
            all_results.extend(results)
            counts[name] = len(results)
        except Exception:
            print(f"[{name}] FAILED — skipping")
            traceback.print_exc()
            counts[name] = 0
    return all_results, counts


def _print_funnel() -> None:
    """Show what each filter dropped this run, so recall losses are visible."""
    if not FUNNEL_STATS:
        print("[funnel] no items dropped by filters")
        return
    for name, stats in sorted(FUNNEL_STATS.items()):
        examples = "; ".join(stats["examples"])
        print(f"[funnel] {name} dropped {stats['dropped']} (e.g. {examples})")


def _page_url() -> str:
    """Build the published GitHub Pages URL when running in GitHub Actions."""
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER")
    repo_full = os.environ.get("GITHUB_REPOSITORY", "")  # "owner/repo"
    repo = repo_full.split("/", 1)[1] if "/" in repo_full else ""
    if owner and repo:
        return f"https://{owner}.github.io/{repo}/"
    return PAGE_URL_FALLBACK


async def main():
    print("=== Contract Assignment Scraper ===")

    raw, source_counts = await run_all_scrapers()
    print(f"\n[dedup] {len(raw)} total → ", end="")

    deduped = deduplicate(raw)
    print(f"{len(deduped)} after deduplication")

    contract_only = [
        a for a in deduped
        if is_contract(a.title, a.description, source=a.source, broker=a.is_broker)
    ]
    print(f"[contract-filter] {len(deduped)} total -> {len(contract_only)} contract/freelance")
    _print_funnel()

    broken_sources = check_source_health(source_counts)
    if broken_sources:
        print(f"[health] sources that yielded 0 (had results last run): {', '.join(broken_sources)}")

    marked = mark_new(contract_only)
    new_count = sum(1 for a in marked if a.is_new)
    print(f"[state] {new_count} new assignments")

    print(f"[summarizer] Summarizing {len(marked)} assignments...")
    summarized = summarize(marked)

    unscored = sum(1 for a in summarized if not a.relevance_score)
    warnings = []
    if summarized and unscored > len(summarized) / 2:
        warnings.append(
            f"LLM-poängsättningen misslyckades för {unscored} av {len(summarized)} uppdrag "
            "— kontrollera GITHUB_MODELS_TOKEN och ratelimit."
        )
    if broken_sources:
        warnings.append(
            f"Källor som gav 0 träffar (gav träffar förra körningen): {', '.join(broken_sources)}."
        )
    warning = " ".join(warnings)
    if warning:
        print(f"[health] WARNING: {warning}")

    funnel_note = " · ".join(
        f"{name}: −{stats['dropped']}" for name, stats in sorted(FUNNEL_STATS.items())
    )

    generate(summarized, warning=warning, funnel_note=funnel_note)

    post_to_discord(summarized, page_url=_page_url(), warning=warning)
    print("\n✅ Done")


if __name__ == "__main__":
    try:  # ensure emoji/arrows in log output don't crash a Windows console
        import sys
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    asyncio.run(main())
