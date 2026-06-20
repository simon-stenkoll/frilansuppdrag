"""Scraper using JobTech Dev API (Swedish government, free, no auth).

Covers all jobs posted via Arbetsförmedlingen / Platsbanken.
Filters for freelance / contract assignments only.
"""

import httpx
from src.models import Assignment
from src.scrapers.utils import clean_text, polite_delay, is_contract, has_contract_signal
from src.config import KEYWORDS

API_URL = "https://jobsearch.api.jobtechdev.se/search"
MUNICIPALITY_STOCKHOLM = "0180"
RESULTS_PER_QUERY = 50

# Subset of KEYWORDS that work well as search queries (avoid too-generic terms)
SEARCH_QUERIES = [
    "data engineer",
    "BI developer",
    "business intelligence",
    "data analyst",
    "power bi",
    "databricks",
    "data warehouse",
    "microsoft fabric",
    "ETL",
    "analytics engineer",
    "data platform",
    "snowflake",
    "pyspark",
    "dbt",
    "azure data factory",
]


async def scrape() -> list[Assignment]:
    results: list[Assignment] = []
    seen_ids: set[str] = set()

    async with httpx.AsyncClient(timeout=15) as client:
        for query in SEARCH_QUERIES:
            await polite_delay()
            try:
                resp = await client.get(
                    API_URL,
                    params={
                        "q": query,
                        "municipality": MUNICIPALITY_STOCKHOLM,
                        "limit": RESULTS_PER_QUERY,
                    },
                )
                resp.raise_for_status()
            except httpx.HTTPError:
                continue

            data = resp.json()
            for hit in data.get("hits", []):
                hit_id = hit.get("id", "")
                if hit_id in seen_ids:
                    continue
                seen_ids.add(hit_id)

                headline = clean_text(hit.get("headline", ""))
                if not headline:
                    continue

                description_text = hit.get("description", {}).get("text", "")
                # Check relevance: headline or description must contain a keyword
                combined = (headline + " " + description_text).lower()
                if not any(kw.lower() in combined for kw in KEYWORDS):
                    continue

                # Structured guard from JobTech metadata: skip obvious permanent listings
                # unless contract wording is explicit in title/description.
                employment_label = clean_text(
                    (hit.get("employment_type", {}) or {}).get("label", "")
                ).lower()
                if employment_label in {
                    "vanlig anställning",
                    "tillsvidareanställning (inkl. eventuell provanställning)",
                } and not has_contract_signal(headline, description_text):
                    continue

                # Filter: only keep freelance / contract assignments
                if not is_contract(headline, description_text, source="Platsbanken"):
                    continue

                employer = hit.get("employer", {}).get("name", "")
                workplace = hit.get("workplace_address", {})
                municipality = workplace.get("municipality", "Stockholm")
                url = hit.get("webpage_url", "")

                results.append(Assignment(
                    title=headline,
                    company=employer,
                    location=municipality or "Stockholm",
                    description=clean_text(description_text[:500]),
                    url=url,
                    source="Platsbanken",
                ))

    return results
