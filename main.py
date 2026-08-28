"""Main orchestrator: runs all scrapers, deduplicates, classifies, generates digest."""

import asyncio
import os
import traceback
from src.scrapers import jobtech, broker_apis, cinode_market, verama
from src.dedup import deduplicate
from src.state import flag_new, persist_seen
from src.classifier import classify
from src.digest import generate
from src.notify import send_email
from src.config import DISABLED_SCRAPERS, PAGE_URL_FALLBACK

SCRAPERS = [
    ("Platsbanken (JobTech)", jobtech.scrape),
    ("Broker APIs", broker_apis.scrape),
    ("Cinode Market", cinode_market.scrape),
    ("Verama", verama.scrape),
]


async def run_all_scrapers():
    all_results = []
    for name, scrape_fn in SCRAPERS:
        if name in DISABLED_SCRAPERS:
            print(f"[{name}] SKIPPED — temporarily disabled")
            continue
        try:
            results = await scrape_fn()
            print(f"[{name}] {len(results)} assignments found")
            all_results.extend(results)
        except Exception:
            print(f"[{name}] FAILED — skipping")
            traceback.print_exc()
    return all_results


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

    raw = await run_all_scrapers()
    print(f"\n[dedup] {len(raw)} total → ", end="")

    deduped = deduplicate(raw)
    print(f"{len(deduped)} after deduplication")

    marked = flag_new(deduped)
    new_count = sum(1 for a in marked if a.is_new)
    print(f"[state] {new_count} new assignments")

    print(f"[classifier] Klassificerar {len(marked)} uppdrag...")
    classified = classify(marked)

    persist_seen(classified)

    unclassified = sum(1 for a in classified if not a.classified)
    warning = ""
    if classified and unclassified > len(classified) / 2:
        warning = (
            f"LLM-klassificeringen misslyckades för {unclassified} av {len(classified)} "
            "uppdrag, kontrollera GITHUB_MODELS_TOKEN, budget och ratelimit."
        )
        print(f"[health] WARNING: {warning}")

    generate(classified, warning=warning)

    send_email(classified, page_url=_page_url(), warning=warning)
    print("\n✅ Done")


if __name__ == "__main__":
    try:  # ensure emoji/arrows in log output don't crash a Windows console
        import sys
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    asyncio.run(main())
