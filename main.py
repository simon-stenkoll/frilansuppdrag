"""Main orchestrator: runs all scrapers, deduplicates, classifies, generates digest."""

import asyncio
import os
import traceback
from datetime import date
from src.scrapers import jobtech, broker_apis, portal_llm, cinode_market, verama
from src.dedup import deduplicate
from src.state import flag_new, persist_seen
from src.classifier import ClassifyStats, LlmBudget, classify
from src.digest import generate
from src.notify import send_alert, send_email
from src.config import ALERT_LLM_DOWN_SUBJECT, DISABLED_SCRAPERS, PAGE_URL_FALLBACK
from src.llm import api_key_env_name

SCRAPERS = [
    ("Platsbanken (JobTech)", jobtech.scrape),
    ("Broker APIs", broker_apis.scrape),
    ("Broker Portals (LLM)", portal_llm.scrape),
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


def build_alert_body(stats: ClassifyStats, page_url: str = "") -> str:
    """Body of the degraded-run alert mail. Pure, so it can be checked without SMTP."""
    reason = stats.auth_error or (
        "inget LLM-anrop lyckades, samtliga uppdrag sköts upp till nästa körning"
    )
    lines = [
        f"Datum: {date.today().isoformat()}",
        f"LLM-klassificeringen gav 0 lyckade svar för {stats.needed_llm} uppdrag "
        f"({stats.cached} kom från cache, {stats.failed} misslyckade, "
        f"{stats.deferred} uppskjutna).",
        f"Orsak: {reason}",
        "Digesten visar därför inga kvalificerade uppdrag och dagens mail är tomt.",
        f"Kontrollera {api_key_env_name()}-secreten (giltig nyckel, projektet inte "
        "spärrat) och kvoten hos leverantören.",
    ]
    if page_url:
        lines.append(f"Digest: {page_url}")
    return "\n".join(lines)


async def main() -> int:
    """Run the pipeline. Returns the process exit code (1 on a degraded run)."""
    print("=== Contract Assignment Scraper ===")

    # One LLM budget for the whole run, shared by portal extraction and classification.
    # Portal extraction happens inside the scrapers, before classify(), so main owns the
    # counter. The scraper interface stays `async def scrape()`, so portal_llm receives
    # the instance through set_budget() while classify() takes it as an argument.
    budget = LlmBudget()
    portal_llm.set_budget(budget)

    raw = await run_all_scrapers()
    print(f"\n[dedup] {len(raw)} total → ", end="")

    deduped = deduplicate(raw)
    print(f"{len(deduped)} after deduplication")

    marked = flag_new(deduped)
    new_count = sum(1 for a in marked if a.is_new)
    print(f"[state] {new_count} new assignments")

    print(f"[classifier] Klassificerar {len(marked)} uppdrag...")
    stats = ClassifyStats()
    classified = classify(marked, budget=budget, stats=stats)

    persist_seen(classified)

    unclassified = sum(1 for a in classified if not a.classified)
    warning = ""
    if classified and unclassified > len(classified) / 2:
        warning = (
            f"LLM-klassificeringen misslyckades för {unclassified} av {len(classified)} "
            f"uppdrag, kontrollera {api_key_env_name()}, budget och ratelimit."
        )
        print(f"[health] WARNING: {warning}")

    page_url = _page_url()
    generate(classified, warning=warning)

    send_email(classified, page_url=page_url, warning=warning)

    # Total LLM outage: digest and state are already written, so alert loudly and let
    # the process exit non-zero to turn the workflow red.
    if stats.is_degraded:
        body = build_alert_body(stats, page_url)
        print(f"[health] DEGRADERAD KÖRNING: {ALERT_LLM_DOWN_SUBJECT}")
        print(body)
        send_alert(ALERT_LLM_DOWN_SUBJECT, body)
        print("\n❌ Degraderad körning, avslutar med exitkod 1")
        return 1

    print("\n✅ Done")
    return 0


if __name__ == "__main__":
    import sys

    try:  # ensure emoji/arrows in log output don't crash a Windows console
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(asyncio.run(main()))
