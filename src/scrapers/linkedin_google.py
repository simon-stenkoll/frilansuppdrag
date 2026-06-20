"""LinkedIn jobs via Google search (avoids LinkedIn's scraping blocks)."""

import re
import httpx
from bs4 import BeautifulSoup
from src.config import GOOGLE_LINKEDIN_QUERIES
from src.models import Assignment
from src.scrapers.utils import make_client, is_relevant, clean_text, polite_delay

GOOGLE_URL = "https://www.google.com/search"


async def scrape() -> list[Assignment]:
    results: list[Assignment] = []
    seen_urls: set[str] = set()

    async with make_client() as client:
        for query in GOOGLE_LINKEDIN_QUERIES:
            await polite_delay()
            try:
                resp = await client.get(
                    GOOGLE_URL,
                    params={"q": query, "num": "20"},
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/124.0.0.0 Safari/537.36"
                        )
                    },
                )
                resp.raise_for_status()
            except httpx.HTTPError:
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            # Google search result links
            for a in soup.select("a[href]"):
                href = a.get("href", "")
                # Extract actual URL from Google's redirect wrapper
                match = re.search(r"/url\?q=(https://www\.linkedin\.com/jobs/[^&]+)", href)
                if not match:
                    if "linkedin.com/jobs" in href and href.startswith("http"):
                        url = href.split("?")[0]
                    else:
                        continue
                else:
                    url = match.group(1)

                if url in seen_urls:
                    continue
                seen_urls.add(url)

                # Title comes from the link text or parent heading
                title = clean_text(a.get_text())
                if not title or len(title) < 8:
                    parent = a.find_parent(["h3", "div"])
                    title = clean_text(parent.get_text()[:120]) if parent else ""
                if not title:
                    continue
                if not is_relevant(title):
                    continue

                results.append(Assignment(
                    title=title,
                    company="(via LinkedIn)",
                    location="Stockholm",
                    description="",
                    url=url,
                    source="LinkedIn (Google)",
                ))

    return results
