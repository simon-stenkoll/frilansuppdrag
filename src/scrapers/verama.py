"""Scraper for Verama, Ework Group's assignment marketplace.

app.verama.com exposes an open JSON API without auth. The list endpoint returns
a Spring Page (content / totalElements / last / number) but carries no
description, so the description is fetched per assignment from the detail
endpoint. To keep that cheap the country, location and keyword filters run on
the list payload first, and only the survivors get a detail request.

The source string "Verama" is part of the dedup and seen-state keys, so it must
stay exactly as it is.
"""

import httpx
from bs4 import BeautifulSoup

from src.config import (
    VERAMA_API_URL,
    VERAMA_DETAIL_URL,
    VERAMA_JOB_URL,
    VERAMA_PAGE_SIZE,
    VERAMA_MAX_PAGES,
)
from src.models import Assignment
from src.scrapers.utils import make_client, is_relevant, clean_text, polite_delay

SOURCE = "Verama"

# Longest description kept from a detail record (plain text, LLM prompt budget).
DESCRIPTION_MAX_CHARS = 2000

# Remote share (percent) at which an assignment outside Stockholm still counts.
MIN_REMOTENESS = 50


# ─── MAIN ENTRY POINT ────────────────────────────────────────────────────────

async def scrape() -> list[Assignment]:
    out: list[Assignment] = []

    async with make_client() as client:
        items = await _fetch_list(client)
        candidates = [item for item in items if _is_candidate(item)]
        print(f"[{SOURCE}] {len(items)} listed, {len(candidates)} candidates for detail fetch")

        for item in candidates:
            await polite_delay()
            detail = await _fetch_detail(client, item["id"])
            description = _description(item, detail)
            out.append(Assignment(
                title=str(item.get("title") or "")[:150],
                company=_company(item),
                location=_location_text(item) or "Sverige",
                description=description,
                url=VERAMA_JOB_URL.format(id=item["id"]),
                source=SOURCE,
            ))

    return out


# ─── LIST ENDPOINT ───────────────────────────────────────────────────────────

async def _fetch_list(client: httpx.AsyncClient) -> list[dict]:
    """Page through the public job-request list (one page normally suffices)."""
    out: list[dict] = []
    seen_ids: set[int] = set()

    for page in range(VERAMA_MAX_PAGES):
        if page:
            await polite_delay()
        try:
            resp = await client.get(
                VERAMA_API_URL,
                params={"size": VERAMA_PAGE_SIZE, "page": page},
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as e:
            print(f"[{SOURCE}] list page {page} failed: {type(e).__name__}")
            break

        items = data.get("content") or []
        for item in items:
            if not isinstance(item, dict):
                continue
            item_id = item.get("id")
            if not isinstance(item_id, int) or item_id in seen_ids:
                continue
            if not item.get("title"):
                continue
            seen_ids.add(item_id)
            out.append(item)

        if data.get("last") or not items:
            break

    return out


def _is_candidate(item: dict) -> bool:
    """Cheap pre-detail filter: Sweden, Stockholm-or-remote, keyword match."""
    locations = [loc for loc in (item.get("locations") or []) if isinstance(loc, dict)]
    # The country string is localised ("Sverige" today, "Sweden" before), so the
    # country code is the only stable signal.
    if not any(loc.get("countryCode") == "SWE" for loc in locations):
        return False

    cities = " ".join((loc.get("city") or "") for loc in locations).lower()
    remoteness = item.get("remoteness") or 0
    if "stockholm" not in cities and remoteness < MIN_REMOTENESS:
        return False

    return is_relevant(str(item.get("title") or ""), _skills_text(item))


# ─── DETAIL ENDPOINT ─────────────────────────────────────────────────────────

async def _fetch_detail(client: httpx.AsyncClient, item_id: int) -> dict:
    """Return the detail record for one job request, or {} on failure."""
    try:
        resp = await client.get(
            VERAMA_DETAIL_URL.format(id=item_id),
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError) as e:
        print(f"[{SOURCE}] detail fetch failed for {item_id}: {type(e).__name__}")
        return {}
    return data if isinstance(data, dict) else {}


# ─── FIELD HELPERS ───────────────────────────────────────────────────────────

def _skills_text(item: dict) -> str:
    names = [
        (s.get("skill") or {}).get("name") or ""
        for s in (item.get("skills") or [])
        if isinstance(s, dict)
    ]
    return ", ".join(n for n in names if n)


def _location_text(item: dict) -> str:
    """Combine city names and remoteness into one location string."""
    cities = [
        loc.get("city") or ""
        for loc in (item.get("locations") or [])
        if isinstance(loc, dict)
    ]
    parts = [c for c in cities if c]
    if (item.get("remoteness") or 0) >= MIN_REMOTENESS:
        parts.append("Remote")
    return ", ".join(dict.fromkeys(parts))


def _company(item: dict) -> str:
    """Prefer the named client; `client` is usually null on public listings."""
    for key in ("client", "legalEntityClient"):
        value = item.get(key)
        if isinstance(value, dict):
            name = clean_text(value.get("name") or "")
            if name:
                return name
    return f"(via {SOURCE})"


def _description(item: dict, detail: dict) -> str:
    """Plain-text description built from the detail HTML plus list metadata."""
    parts = [_strip_html(detail.get("description"))]

    requirements = _strip_html(detail.get("requirements"))
    if requirements:
        parts.append(f"Krav: {requirements}")

    skills = _skills_text(item)
    if skills:
        parts.append(f"Kompetenser: {skills}")
    if item.get("level"):
        parts.append(f"Nivå: {item['level']}")
    if item.get("startDate"):
        parts.append(f"Start: {item['startDate']}")
    if item.get("hoursPerWeek"):
        parts.append(f"{item['hoursPerWeek']} h/vecka")

    return " · ".join(p for p in parts if p)[:DESCRIPTION_MAX_CHARS]


def _strip_html(value) -> str:
    """Flatten an HTML string to plain text; anything not a string yields ""."""
    if not isinstance(value, str) or not value:
        return ""
    return clean_text(BeautifulSoup(value, "html.parser").get_text(" ", strip=True))
