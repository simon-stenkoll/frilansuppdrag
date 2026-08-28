"""Scraper for Cinode Market, Cinode's public assignment marketplace.

market.cinode.com serves plain server-rendered HTML with no login and no bot
protection (cinode.com and app.cinode.com sit behind Cloudflare and are useless
for scraping). The listing at /requests shows ~20 cards per page and paginates
through a base64 cursor published on the load-more button as `data-next-cursor`;
the next page is GET /requests?nextCursor=<cursor>.

To stay polite the detail page is fetched only for cards that already pass the
cheap title/location filters, so a full run costs ~8 listing requests plus one
request per genuine candidate.

The source string "Cinode Market" is part of the dedup and seen-state keys, so
it must stay exactly as it is.
"""

from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from src.config import CINODE_LIST_URL, CINODE_MAX_PAGES
from src.models import Assignment
from src.scrapers.utils import (
    make_client,
    is_relevant,
    is_in_stockholm,
    clean_text,
    polite_delay,
)

SOURCE = "Cinode Market"

# Longest description kept from a detail page (plain text, LLM prompt budget).
DESCRIPTION_MAX_CHARS = 2000


# ─── MAIN ENTRY POINT ────────────────────────────────────────────────────────

async def scrape() -> list[Assignment]:
    async with make_client() as client:
        candidates = await _collect_candidates(client)
        out: list[Assignment] = []
        for assignment in candidates:
            await polite_delay()
            description = await _fetch_description(client, assignment.url)
            if description:
                assignment.description = description
            out.append(assignment)
    return out


# ─── LISTING ─────────────────────────────────────────────────────────────────

async def _collect_candidates(client: httpx.AsyncClient) -> list[Assignment]:
    """Walk the cursor-paginated listing and return cards worth a detail fetch."""
    out: list[Assignment] = []
    seen_urls: set[str] = set()
    cursor: str | None = None

    for page in range(CINODE_MAX_PAGES):
        if page:
            await polite_delay()
        params = {"nextCursor": cursor} if cursor else None
        try:
            resp = await client.get(CINODE_LIST_URL, params=params)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            print(f"[{SOURCE}] listing page {page} failed: {type(e).__name__}")
            break

        soup = BeautifulSoup(resp.text, "html.parser")
        cards = soup.select(".requests-list__card")
        if not cards:
            break

        for card in cards:
            assignment = _parse_card(card, seen_urls)
            if assignment:
                out.append(assignment)

        button = soup.select_one("#load-more-button")
        cursor = button.get("data-next-cursor") if button else None
        if not cursor:
            break

    return out


def _parse_card(card, seen_urls: set[str]) -> Assignment | None:
    """Turn one listing card into an Assignment, or None if it is filtered out."""
    link = card.select_one("a.list__heading")
    href = card.get("data-href") or (link.get("href") if link else "")
    if not href or not link:
        return None
    url = urljoin(CINODE_LIST_URL, href)
    if url in seen_urls:
        return None

    title = clean_text(link.get_text())
    if len(title) < 5:
        return None
    if not is_relevant(title):
        return None

    location = _card_location(card)
    if location and not is_in_stockholm(location):
        return None

    seen_urls.add(url)
    return Assignment(
        title=title[:150],
        company=_card_company(card),
        location=location or "Sverige",
        description="",
        url=url,
        source=SOURCE,
    )


def _card_location(card) -> str:
    """Read the city plus its remote share, e.g. "Stockholm (100% remote)"."""
    for item in card.select(".list__details .focus__item"):
        if item.select_one('a[href*="/requests/city/"]'):
            return clean_text(item.get_text(" "))
    return ""


def _card_company(card) -> str:
    company = card.select_one(".requests-list__card-company")
    name = clean_text(company.get_text()) if company else ""
    return name or f"(via {SOURCE})"


# ─── DETAIL PAGE ─────────────────────────────────────────────────────────────

async def _fetch_description(client: httpx.AsyncClient, url: str) -> str:
    """Return the plain-text assignment description, or "" when unavailable."""
    try:
        resp = await client.get(url)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        print(f"[{SOURCE}] detail fetch failed for {url}: {type(e).__name__}")
        return ""

    soup = BeautifulSoup(resp.text, "html.parser")
    body = soup.select_one(".wysiwyg-output")
    if body is None:
        return ""
    text = clean_text(body.get_text(" "))

    skills = [clean_text(s.get_text()) for s in soup.select(".details__skill")]
    skills = [s for s in skills if s]
    if skills:
        text = f"{text} Önskade kompetenser: {', '.join(skills)}"

    return text[:DESCRIPTION_MAX_CHARS]
