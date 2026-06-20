"""Scraper for brainville.com assignments."""

import httpx
from bs4 import BeautifulSoup
from src.models import Assignment
from src.scrapers.utils import make_client, is_relevant, clean_text, polite_delay

BASE_URL = "https://www.brainville.com"
SEARCH_URL = f"{BASE_URL}/assignments"
SEARCH_QUERIES = ["data", "analytics", "BI"]


async def scrape() -> list[Assignment]:
    results: list[Assignment] = []
    seen_urls: set[str] = set()

    async with make_client() as client:
        for query in SEARCH_QUERIES:
            await polite_delay()
            try:
                resp = await client.get(SEARCH_URL, params={"search": query, "country": "SE"})
                resp.raise_for_status()
            except httpx.HTTPError:
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            cards = soup.select("div.assignment, article.assignment, .assignment-item, div[class*='AssignmentCard']")
            if not cards:
                cards = soup.select("a[href*='/assignments/']")

            for card in cards:
                title_el = card.select_one("h2, h3, .title, strong")
                title = clean_text(title_el.get_text() if title_el else card.get_text()[:80])
                if not title:
                    continue

                location_el = card.select_one(".location, .city, [class*='location']")
                location = clean_text(location_el.get_text() if location_el else "")

                href = card.get("href") or (card.select_one("a") and card.select_one("a").get("href")) or ""
                url = href if href.startswith("http") else f"{BASE_URL}{href}"

                desc_el = card.select_one("p, .description, .summary")
                description = clean_text(desc_el.get_text() if desc_el else "")

                if not is_relevant(title, description):
                    continue
                if url in seen_urls:
                    continue
                seen_urls.add(url)

                results.append(Assignment(
                    title=title,
                    company="(via Brainville)",
                    location=location or "Sweden",
                    description=description[:500],
                    url=url,
                    source="Brainville",
                ))

    return results
