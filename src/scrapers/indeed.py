"""Scraper for se.indeed.com."""

import httpx
from bs4 import BeautifulSoup
from src.models import Assignment
from src.scrapers.utils import make_client, is_relevant, is_in_stockholm, clean_text, polite_delay, is_contract

SEARCH_QUERIES = [
    "data engineer konsult",
    "BI developer konsult",
    "Microsoft Fabric",
    "data analytics konsult",
]
BASE_URL = "https://se.indeed.com/jobs"


async def scrape() -> list[Assignment]:
    results: list[Assignment] = []
    seen_urls: set[str] = set()

    async with make_client() as client:
        for query in SEARCH_QUERIES:
            await polite_delay()
            try:
                resp = await client.get(
                    BASE_URL,
                    params={"q": query, "l": "Stockholm", "sc": "0kf:attr(DSQF7);"},
                )
                resp.raise_for_status()
            except httpx.HTTPError:
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            cards = soup.select("div.job_seen_beacon, div.jobCard_mainContent, div[class*='CardWrapper']")

            for card in cards:
                title_el = card.select_one("h2.jobTitle span[title], h2.jobTitle, a.jcs-JobTitle")
                title = clean_text(title_el.get_text() if title_el else "")
                if not title:
                    continue

                company_el = card.select_one("[data-testid='company-name'], .companyName, span.company")
                company = clean_text(company_el.get_text() if company_el else "")

                location_el = card.select_one("[data-testid='text-location'], .companyLocation")
                location = clean_text(location_el.get_text() if location_el else "Stockholm")

                link_el = card.select_one("a[href*='/jobb/'], a[id*='job_']")
                href = link_el.get("href") if link_el else ""
                url = href if href.startswith("http") else f"https://se.indeed.com{href}"

                snippet_el = card.select_one(".job-snippet, ul.jobCardShelfItem")
                description = clean_text(snippet_el.get_text() if snippet_el else "")

                if not is_relevant(title, description):
                    continue
                if not is_contract(title, description, source="Indeed"):
                    continue
                if url in seen_urls:
                    continue
                seen_urls.add(url)

                results.append(Assignment(
                    title=title,
                    company=company,
                    location=location,
                    description=description[:500],
                    url=url,
                    source="Indeed",
                ))

    return results
