"""Scraper for ework.se/uppdrag (public assignment board)."""

import httpx
from bs4 import BeautifulSoup
from src.models import Assignment
from src.scrapers.utils import make_client, is_relevant, is_in_stockholm, clean_text, polite_delay


SEARCH_URL = "https://www.ework.se/uppdrag"
SEARCH_QUERIES = ["data", "BI", "analytics"]


async def scrape() -> list[Assignment]:
    results: list[Assignment] = []
    async with make_client() as client:
        for query in SEARCH_QUERIES:
            await polite_delay()
            try:
                resp = await client.get(SEARCH_URL, params={"q": query, "location": "Stockholm"})
                resp.raise_for_status()
            except httpx.HTTPError:
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            # Ework uses article cards with class "assignment-card" or similar
            cards = soup.select("article.uppdrag, .assignment-card, .uppdrag-item, li.job-item")
            if not cards:
                # Fallback: try generic link-based parsing
                cards = soup.select("a[href*='/uppdrag/']")

            for card in cards:
                title = clean_text(card.select_one("h2, h3, .title, .uppdrag-title, strong") and
                                   card.select_one("h2, h3, .title, .uppdrag-title, strong").get_text() or
                                   card.get_text())
                if not title:
                    continue
                location_el = card.select_one(".location, .ort, [class*='location']")
                location = clean_text(location_el.get_text() if location_el else "Stockholm")
                desc_el = card.select_one("p, .description, .ingress")
                description = clean_text(desc_el.get_text() if desc_el else "")
                href = card.get("href") or (card.select_one("a") and card.select_one("a").get("href")) or ""
                url = href if href.startswith("http") else f"https://www.ework.se{href}"

                if not is_relevant(title, description):
                    continue
                if not is_in_stockholm(location):
                    continue

                results.append(Assignment(
                    title=title,
                    company="(via Ework)",
                    location=location,
                    description=description[:500],
                    url=url,
                    source="Ework",
                ))

    return _deduplicate(results)


def _deduplicate(items: list[Assignment]) -> list[Assignment]:
    seen: set[str] = set()
    out: list[Assignment] = []
    for item in items:
        if item.url not in seen:
            seen.add(item.url)
            out.append(item)
    return out
