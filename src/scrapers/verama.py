"""Scraper for Verama — Ework's assignment platform with a public JSON API.

Replaces the old ework.py scraper (ework.se is blocked by anti-scraping, but
its assignments are published on app.verama.com which serves plain JSON).
"""

import httpx

from src.config import (
    VERAMA_API_URL,
    VERAMA_JOB_URL,
    VERAMA_PAGE_SIZE,
    VERAMA_MAX_PAGES,
)
from src.models import Assignment
from src.scrapers.utils import make_client, is_relevant, polite_delay

SOURCE = "Ework (Verama)"


def _location_text(item: dict) -> str:
    """Combine city names and remoteness into one location string."""
    cities = [
        loc.get("city") or ""
        for loc in item.get("locations") or []
        if isinstance(loc, dict)
    ]
    remoteness = item.get("remoteness") or 0
    parts = [c for c in cities if c]
    if remoteness >= 50:
        parts.append("Remote")
    return ", ".join(parts)


def _in_sweden(item: dict) -> bool:
    return any(
        (loc.get("countryCode") == "SWE" or loc.get("country") == "Sweden")
        for loc in item.get("locations") or []
        if isinstance(loc, dict)
    )


def _description(item: dict) -> str:
    """Build a keyword-matchable description from skills, level, and dates."""
    skills = [
        (s.get("skill") or {}).get("name") or ""
        for s in item.get("skills") or []
        if isinstance(s, dict)
    ]
    parts = []
    if skills:
        parts.append("Skills: " + ", ".join(s for s in skills if s))
    if item.get("level"):
        parts.append(f"Level: {item['level']}")
    if item.get("startDate"):
        parts.append(f"Start: {item['startDate']}")
    if item.get("hoursPerWeek"):
        parts.append(f"{item['hoursPerWeek']} h/week")
    return " · ".join(parts)


async def scrape() -> list[Assignment]:
    out: list[Assignment] = []
    seen_ids: set[str] = set()

    async with make_client() as client:
        for page in range(VERAMA_MAX_PAGES):
            await polite_delay()
            try:
                resp = await client.get(
                    VERAMA_API_URL,
                    params={"size": VERAMA_PAGE_SIZE, "page": page},
                    headers={"Accept": "application/json"},
                )
                resp.raise_for_status()
                data = resp.json()
            except (httpx.HTTPError, ValueError):
                break

            items = data.get("content") or []
            for item in items:
                if not isinstance(item, dict):
                    continue
                item_id = str(item.get("id") or "")
                title = item.get("title") or ""
                if not item_id or item_id in seen_ids or not title:
                    continue
                seen_ids.add(item_id)

                if not _in_sweden(item):
                    continue
                location = _location_text(item)
                # Keep Stockholm-area or majority-remote assignments only.
                if "stockholm" not in location.lower() and (item.get("remoteness") or 0) < 50:
                    continue
                description = _description(item)
                if not is_relevant(title, description):
                    continue

                client_info = item.get("client") or {}
                company = (
                    client_info.get("name") if isinstance(client_info, dict) else ""
                ) or "(via Ework/Verama)"
                out.append(Assignment(
                    title=title[:150],
                    company=company,
                    location=location or "Sweden",
                    description=description[:500],
                    url=VERAMA_JOB_URL.format(id=item_id),
                    source=SOURCE,
                    is_broker=True,
                ))

            if data.get("last") or not items:
                break

    return out
