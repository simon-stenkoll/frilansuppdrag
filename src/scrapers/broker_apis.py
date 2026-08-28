"""Scrapers for the Swedish brokers that expose a public JSON/REST API.

A Society (JSON API), Upgraded People (WordPress REST) and KeyMan (WordPress REST)
are the only broker sources that deliver assignments reliably, so they live here on
their own. The hand written HTML parsers they used to share a module with produced
almost nothing and were removed.

Source strings ("A Society", "Upgraded People", "KeyMan") are part of the dedup and
seen-state keys, so they must stay exactly as they are.
"""

import re

import httpx
from bs4 import BeautifulSoup

from src.models import Assignment
from src.scrapers.utils import (
    make_client,
    is_relevant,
    is_in_stockholm,
    clean_text,
    polite_delay,
)

# ─── CONSTANTS ───────────────────────────────────────────────────────────────

UPGRADED_ASSIGNMENTS_API = "https://upgraded.se/wp-json/wp/v2/konsultuppdrag"
UPGRADED_LOCATION_API = "https://upgraded.se/wp-json/wp/v2/ort/{ort_id}"
ASOCIETY_API = "https://www.asocietygroup.com/api/assignments"
KEYMAN_API = "https://www.keyman.se/sv/wp-json/wp/v2/posts"


# ─── MAIN ENTRY POINT ────────────────────────────────────────────────────────

async def scrape() -> list[Assignment]:
    results: list[Assignment] = []
    seen_urls: set[str] = set()

    async with make_client() as client:
        results.extend(await _scrape_asociety_api(client, seen_urls))
        results.extend(await _scrape_upgraded_api(client, seen_urls))
        results.extend(await _scrape_keyman_api(client, seen_urls))

    return results


# ─── SHARED HELPERS ──────────────────────────────────────────────────────────

def _try_assignment(
    title: str, description: str, location: str, url: str,
    source: str, seen_urls: set[str],
) -> Assignment | None:
    """Create an Assignment if it passes the cheap keyword and location filters.

    The old keyword contract filter is gone: the LLM classifier decides whether a
    listing is a real assignment.
    """
    if not title or len(title) < 5 or not url or url in seen_urls:
        return None
    if not is_relevant(title, description):
        return None
    if location and not is_in_stockholm(location):
        return None
    seen_urls.add(url)
    return Assignment(
        title=title[:150],
        company=f"(via {source})",
        location=location or "Sweden",
        description=description[:500],
        url=url,
        source=source,
    )


def _strip_html(value: str) -> str:
    return clean_text(BeautifulSoup(value or "", "html.parser").get_text(" ", strip=True))


# ─── API SCRAPERS ────────────────────────────────────────────────────────────

async def _scrape_asociety_api(client: httpx.AsyncClient, seen_urls: set[str]) -> list[Assignment]:
    """Fetch assignments from A Society's public JSON API."""
    out: list[Assignment] = []
    await polite_delay()
    try:
        resp = await client.get(ASOCIETY_API)
        resp.raise_for_status()
    except httpx.HTTPError:
        return out

    try:
        items = resp.json()
    except Exception:
        return out
    if not isinstance(items, list):
        return out

    for item in items:
        title = clean_text(item.get("requisition_name", ""))
        if not title:
            continue
        description = _strip_html(item.get("requisition_description", ""))
        location = clean_text(item.get("requisition_locationid", ""))
        abstract_id = item.get("abstract_id", "")
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        url = f"https://www.asocietygroup.com/sv/uppdrag/{slug}-{abstract_id}"
        a = _try_assignment(title, description, location, url, "A Society", seen_urls)
        if a:
            out.append(a)
    return out


async def _scrape_upgraded_api(client: httpx.AsyncClient, seen_urls: set[str]) -> list[Assignment]:
    """Fetch assignments from Upgraded's public WordPress API."""
    out: list[Assignment] = []
    ort_cache: dict[int, str] = {}

    for page in range(1, 6):
        await polite_delay()
        try:
            resp = await client.get(
                UPGRADED_ASSIGNMENTS_API,
                params={"per_page": 20, "page": page, "orderby": "date", "order": "desc"},
            )
            if resp.status_code == 400:
                break
            resp.raise_for_status()
        except httpx.HTTPError:
            break

        items = resp.json()
        if not items:
            break

        for item in items:
            title = _strip_html((item.get("title") or {}).get("rendered", ""))
            if not title:
                continue
            description = _strip_html((item.get("excerpt") or {}).get("rendered", ""))
            if not description:
                description = _strip_html((item.get("content") or {}).get("rendered", ""))
            url = clean_text(item.get("link", ""))
            if not url:
                continue
            location = await _resolve_upgraded_locations(client, item.get("ort"), ort_cache)
            if location and not is_in_stockholm(location):
                continue
            if not location and not is_in_stockholm(description):
                continue
            a = _try_assignment(title, description, location, url, "Upgraded People", seen_urls)
            if a:
                out.append(a)
    return out


async def _scrape_keyman_api(client: httpx.AsyncClient, seen_urls: set[str]) -> list[Assignment]:
    """Fetch assignments from KeyMan's public WordPress REST API."""
    out: list[Assignment] = []
    for page in range(1, 8):
        await polite_delay()
        try:
            resp = await client.get(
                KEYMAN_API,
                params={"per_page": 100, "page": page, "orderby": "date", "order": "desc"},
            )
            if resp.status_code == 400:
                break
            resp.raise_for_status()
        except httpx.HTTPError:
            break
        try:
            items = resp.json()
        except Exception:
            break
        if not items:
            break

        for item in items:
            title = _strip_html((item.get("title") or {}).get("rendered", ""))
            if not title:
                continue
            content_html = (item.get("content") or {}).get("rendered", "")
            description = _strip_html((item.get("excerpt") or {}).get("rendered", ""))
            if not description:
                description = _strip_html(content_html)
            url = clean_text(item.get("link", ""))
            if not url:
                continue
            location = _extract_keyman_location(content_html)
            if location and not is_in_stockholm(location):
                continue
            if not location and not is_in_stockholm(description):
                continue
            a = _try_assignment(title, description, location, url, "KeyMan", seen_urls)
            if a:
                out.append(a)
    return out


async def _resolve_upgraded_locations(
    client: httpx.AsyncClient,
    ort_ids: list[int] | int | None,
    cache: dict[int, str],
) -> str:
    ids: list[int] = []
    if isinstance(ort_ids, list):
        ids = [v for v in ort_ids if isinstance(v, int)]
    elif isinstance(ort_ids, int):
        ids = [ort_ids]

    names: list[str] = []
    for ort_id in ids:
        if ort_id not in cache:
            try:
                resp = await client.get(UPGRADED_LOCATION_API.format(ort_id=ort_id))
                if resp.status_code == 200:
                    cache[ort_id] = clean_text(resp.json().get("name", ""))
                else:
                    cache[ort_id] = ""
            except httpx.HTTPError:
                cache[ort_id] = ""
        if cache[ort_id]:
            names.append(cache[ort_id])

    return ", ".join(dict.fromkeys(names))


def _extract_keyman_location(html: str) -> str:
    """Extract location (Ort) from KeyMan post content HTML table."""
    soup = BeautifulSoup(html, "html.parser")
    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) >= 2 and clean_text(cells[0].get_text()).lower() == "ort":
            return clean_text(cells[1].get_text())
    return ""
