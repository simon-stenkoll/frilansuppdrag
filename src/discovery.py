"""Deep discovery of Swedish consultant-broker assignment portals.

Reads Anna Leijon's curated broker list, then digs into each broker's site to
find a page that actually lists assignments. The result is written to
state/portals.json, which the nightly run (src/scrapers/broker_portals.py) reads
so it can focus only on portals that show assignments.

Run occasionally / manually — it is heavy (renders ~130 sites with a browser):

    python -m src.discovery            # full deep discovery → state/portals.json
    python -m src.discovery --probe    # quick HTTP status check of candidates
"""

import asyncio
import json
import os
import sys
from datetime import date
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from src.config import (
    LEIJON_URL,
    PORTALS_STATE_FILE,
    DISCOVERY_IT_KEYWORDS,
    ASSIGNMENT_NAV_KEYWORDS,
    DISCOVERY_MAX_LISTING_LINKS,
    DISCOVERY_CONCURRENCY,
)
from src.scrapers.utils import make_client, BrowserSession, clean_text, polite_delay
from src.scrapers.broker_portals import _extract_from_soup, _base_url


# ─── ANNA LEIJON BROKER LIST ─────────────────────────────────────────────────

def _is_external(href: str) -> bool:
    href = (href or "").lower()
    if not href.startswith("http"):
        return False
    skip = ("annaleijon", "linkedin.", "facebook.", "twitter.", "instagram.", "mailto:")
    return not any(s in href for s in skip)


def _looks_like_portal_link(a) -> bool:
    text = (a.get_text() or "").lower()
    href = (a.get("href") or "").lower()
    blob = text + " " + href
    return any(kw in blob for kw in ("uppdrag", "assignment", "jobb", "/jobs", "lediga", "career"))


def extract_brokers(html: str) -> list[dict]:
    """Parse the broker table into {name, website, uppdragsportal, sector}."""
    soup = BeautifulSoup(html, "html.parser")
    brokers: list[dict] = []
    seen: set[str] = set()

    for table in soup.select("table"):
        for row in table.select("tr"):
            cells = row.select("td")
            if len(cells) < 2:
                continue

            # Name + website come from the first cell's link (Namn column).
            name_link = cells[0].find("a")
            name = clean_text((name_link or cells[0]).get_text())
            if not name or len(name) < 2:
                continue
            key = name.lower()
            if key in seen:
                continue

            website = ""
            if name_link and _is_external(name_link.get("href", "")):
                website = name_link.get("href", "").strip()

            # Uppdragsportal: an external link elsewhere in the row that looks
            # like an assignment portal; otherwise any other external link.
            uppdragsportal = ""
            other_external = ""
            for cell in cells[1:]:
                for a in cell.find_all("a"):
                    href = a.get("href", "").strip()
                    if not _is_external(href):
                        continue
                    if _looks_like_portal_link(a) and not uppdragsportal:
                        uppdragsportal = href
                    elif not other_external:
                        other_external = href
            if not uppdragsportal:
                uppdragsportal = other_external

            if not website and not uppdragsportal:
                continue
            seen.add(key)

            sector = clean_text(cells[1].get_text()) if len(cells) > 1 else ""
            brokers.append({
                "name": name,
                "website": website,
                "uppdragsportal": uppdragsportal,
                "sector": sector,
            })

    return brokers


def filter_it_brokers(brokers: list[dict]) -> list[dict]:
    """Keep brokers whose sector looks IT/tech-relevant (or has no sector)."""
    out = []
    for b in brokers:
        sector = b["sector"].lower()
        if not sector or any(k in sector for k in DISCOVERY_IT_KEYWORDS):
            out.append(b)
    return out


# ─── DEEP CRAWL ──────────────────────────────────────────────────────────────

def _find_listing_links(soup: BeautifulSoup, base: str) -> list[str]:
    """Return candidate assignment-listing URLs found in nav/links on a page."""
    found: list[str] = []
    seen: set[str] = set()
    for a in soup.select("a[href]"):
        href = a.get("href", "").strip()
        if not href or href.startswith("#") or href.startswith("mailto:"):
            continue
        blob = (clean_text(a.get_text()) + " " + href).lower()
        if not any(kw in blob for kw in ASSIGNMENT_NAV_KEYWORDS):
            continue
        url = href if href.startswith("http") else urljoin(base + "/", href)
        # Stay on the same site
        if urlparse(url).netloc and urlparse(url).netloc not in base:
            continue
        if url not in seen:
            seen.add(url)
            found.append(url)
    return found[:DISCOVERY_MAX_LISTING_LINKS]


def _listing_score(soup: BeautifulSoup) -> int:
    """Loose signal that a page lists assignments (even if none match keywords)."""
    count = 0
    for a in soup.select("a[href]"):
        href = (a.get("href") or "").lower()
        if any(s in href for s in ("/uppdrag", "/assignment", "/jobb/", "/jobs/", "/job/", "assignmentid")):
            count += 1
    return count


async def _http_soup(client: httpx.AsyncClient, url: str) -> BeautifulSoup | None:
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except httpx.HTTPError:
        return None


def _probe_soup(soup: BeautifulSoup, url: str, name: str) -> tuple[int, int]:
    """Return (relevant_count, listing_score) for a fetched page."""
    relevant = _extract_from_soup(soup, _base_url(url), name, set())
    return len(relevant), _listing_score(soup)


async def investigate(
    broker: dict, client: httpx.AsyncClient, browser: BrowserSession,
) -> dict:
    """Deep-crawl one broker, returning a portals.json record."""
    name = broker["name"]
    record = {
        "name": name,
        "website": broker.get("website", ""),
        "listing_url": "",
        "method": "http",
        "status": "error",
        "relevant_count": 0,
        "listing_score": 0,
        "last_checked": date.today().isoformat(),
        "last_found": "",
    }

    # 1st candidate: Uppdragsportal link. 2nd: the broker homepage.
    candidates = [u for u in (broker.get("uppdragsportal"), broker.get("website")) if u]
    candidates = list(dict.fromkeys(candidates))  # dedup, keep order
    reached = False
    best_listing = 0

    async def consider(soup, url, method) -> bool:
        """Update record from a fetched page; return True if 'working'."""
        nonlocal reached, best_listing
        reached = True
        relevant, listing = _probe_soup(soup, url, name)
        if relevant >= 1:
            record.update(
                listing_url=url, method=method, status="working",
                relevant_count=relevant, listing_score=listing,
                last_found=date.today().isoformat(),
            )
            return True
        if listing > best_listing:
            best_listing = listing
            record.update(listing_url=url, method=method, listing_score=listing)
        return False

    for url in candidates:
        # Try HTTP first (cheap), then escalate to a rendered browser page.
        for method, fetch in (("http", lambda u: _http_soup(client, u)),
                              ("playwright", lambda u: _render_soup(browser, u))):
            if method == "playwright" and not browser.available:
                continue
            soup = await fetch(url)
            if soup is None:
                continue
            if await consider(soup, url, method):
                return record
            # Follow listing-page links discovered on this page.
            for link in _find_listing_links(soup, _base_url(url)):
                sub = await fetch(link)
                if sub is None:
                    continue
                if await consider(sub, link, method):
                    return record
                await polite_delay()

    if reached:
        record["status"] = "listing" if best_listing >= 3 else "empty"
    return record


async def _render_soup(browser: BrowserSession, url: str) -> BeautifulSoup | None:
    html = await browser.fetch(url)
    return BeautifulSoup(html, "html.parser") if html else None


# ─── ORCHESTRATION ───────────────────────────────────────────────────────────

async def run_discovery() -> list[dict]:
    print("=== Broker portal discovery ===")
    async with make_client() as client:
        try:
            resp = await client.get(LEIJON_URL)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            print(f"Failed to fetch Anna Leijon list: {e}")
            return []

        brokers = filter_it_brokers(extract_brokers(resp.text))
        print(f"Found {len(brokers)} IT-relevant brokers with links\n")

        results: list[dict] = []
        sem = asyncio.Semaphore(DISCOVERY_CONCURRENCY)

        async with BrowserSession() as browser:
            if not browser.available:
                print("[discovery] Playwright unavailable — HTTP-only (JS portals will be missed)\n")

            async def worker(b: dict) -> None:
                async with sem:
                    rec = await investigate(b, client, browser)
                    flag = {"working": "✓", "listing": "·", "empty": " ", "error": "✗"}[rec["status"]]
                    print(f"  [{flag}] {rec['name'][:32]:32s} {rec['status']:8s} "
                          f"rel={rec['relevant_count']} {rec['listing_url']}")
                    results.append(rec)

            await asyncio.gather(*(worker(b) for b in brokers))

    results.sort(key=lambda r: (r["status"] != "working", r["status"] != "listing", r["name"].lower()))
    _save_portals(results)

    working = sum(1 for r in results if r["status"] == "working")
    listing = sum(1 for r in results if r["status"] == "listing")
    print(f"\n=== Done: {working} working, {listing} listing, "
          f"{len(results)} total → {PORTALS_STATE_FILE} ===")
    return results


def _save_portals(results: list[dict]) -> None:
    """Write portals.json, preserving previous last_found where newer data is empty."""
    previous = {}
    if os.path.exists(PORTALS_STATE_FILE):
        try:
            with open(PORTALS_STATE_FILE, "r", encoding="utf-8") as f:
                for p in json.load(f).get("portals", []):
                    previous[p.get("name")] = p
        except (OSError, json.JSONDecodeError, AttributeError):
            previous = {}

    for r in results:
        if not r["last_found"] and r["name"] in previous:
            r["last_found"] = previous[r["name"]].get("last_found", "")

    os.makedirs(os.path.dirname(PORTALS_STATE_FILE), exist_ok=True)
    with open(PORTALS_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"generated": date.today().isoformat(), "portals": results}, f,
                  ensure_ascii=False, indent=2)


async def probe() -> None:
    """Quick HTTP status check of every broker candidate URL (no deep crawl)."""
    async with make_client() as client:
        resp = await client.get(LEIJON_URL)
        brokers = filter_it_brokers(extract_brokers(resp.text))
        print(f"Probing {len(brokers)} brokers\n")
        for b in brokers:
            url = b.get("uppdragsportal") or b.get("website")
            try:
                r = await client.get(url)
                print(f"  {r.status_code}  {b['name'][:32]:32s}  {url}")
            except httpx.HTTPError as e:
                print(f"  ERR  {b['name'][:32]:32s}  {type(e).__name__}")


if __name__ == "__main__":
    if "--probe" in sys.argv:
        asyncio.run(probe())
    else:
        asyncio.run(run_discovery())
