"""Scraper for Swedish broker portals.

Uses API-first integrations where available, then dedicated HTML parsers
for portals with known structure, and finally a generic fallback.
"""

import json
import os
import re
from urllib.parse import urlparse, urljoin, unquote

import httpx
from bs4 import BeautifulSoup
from src.config import BROKER_PORTALS, DISABLED_BROKER_PORTALS, PORTALS_STATE_FILE
from src.models import Assignment
from src.scrapers.utils import (
    make_client,
    is_relevant,
    is_in_stockholm,
    is_contract,
    clean_text,
    polite_delay,
    BrowserSession,
)

# ─── CONSTANTS ───────────────────────────────────────────────────────────────

UPGRADED_ASSIGNMENTS_API = "https://upgraded.se/wp-json/wp/v2/konsultuppdrag"
UPGRADED_LOCATION_API = "https://upgraded.se/wp-json/wp/v2/ort/{ort_id}"
ASOCIETY_API = "https://www.asocietygroup.com/api/assignments"
KEYMAN_API = "https://www.keyman.se/sv/wp-json/wp/v2/posts"
BIOLIT_ASSIGNMENTS_URL = "http://biolit.se/konsultuppdrag"

# Portals handled by dedicated API scrapers (skip in HTML loop)
_API_PORTALS = {"Upgraded People", "A Society", "KeyMan"}

# Portals that are JS SPAs, require login, or have no scrapable content
_UNSCRAPABLE_PORTALS = {
    "Aliant", "Alphadev", "GetWiser", "Wetal", "Paventia", "Pro4u",
    "Sigma", "Afry", "Senterprise", "Donald Davis & Partners",
    "Resursbrist", "Konsultkooperativet", "Seequaly",
}


# ─── MAIN ENTRY POINT ────────────────────────────────────────────────────────

async def scrape() -> list[Assignment]:
    results: list[Assignment] = []
    seen_urls: set[str] = set()
    discovered = _load_working_portals()  # [] when discovery hasn't run yet

    async with make_client() as client:
        # API scrapers (highest quality, always run)
        results.extend(await _scrape_asociety_api(client, seen_urls))
        results.extend(await _scrape_upgraded_api(client, seen_urls))
        results.extend(await _scrape_keyman_api(client, seen_urls))

        # Dedicated HTML scrapers (tuned per portal, always run)
        for portal in BROKER_PORTALS:
            name = portal.get("name")
            scraper_fn = _PORTAL_SCRAPERS.get(name)
            if scraper_fn is None or name in _API_PORTALS | DISABLED_BROKER_PORTALS:
                continue
            await polite_delay()
            results.extend(await scraper_fn(client, portal, seen_urls))

        # Long-tail portals
        if discovered:
            # Focus mode: only portals discovery verified as showing assignments.
            results.extend(await _scrape_discovered_portals(client, discovered, seen_urls))
        else:
            # Pre-discovery fallback: generic HTTP scrape of the seed list.
            for portal in BROKER_PORTALS:
                name = portal.get("name")
                if name in (_API_PORTALS | DISABLED_BROKER_PORTALS
                            | _UNSCRAPABLE_PORTALS | set(_PORTAL_SCRAPERS)):
                    continue
                await polite_delay()
                results.extend(await _scrape_generic_portal(client, portal, seen_urls))

    return results


def _load_working_portals() -> list[dict]:
    """Load portals that discovery marked as showing assignments."""
    if not os.path.exists(PORTALS_STATE_FILE):
        return []
    try:
        with open(PORTALS_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    portals = data.get("portals", []) if isinstance(data, dict) else data
    return [
        p for p in portals
        if isinstance(p, dict) and p.get("status") == "working" and p.get("listing_url")
        and p.get("name") not in DISABLED_BROKER_PORTALS
    ]


async def _scrape_discovered_portals(
    client: httpx.AsyncClient, discovered: list[dict], seen_urls: set[str],
) -> list[Assignment]:
    """Scrape discovery-verified portals not already covered by a dedicated scraper."""
    out: list[Assignment] = []
    handled = _API_PORTALS | set(_PORTAL_SCRAPERS)
    pending = [p for p in discovered if p.get("name") not in handled]

    http_portals = [p for p in pending if p.get("method") != "playwright"]
    js_portals = [p for p in pending if p.get("method") == "playwright"]

    for p in http_portals:
        await polite_delay()
        soup = await _fetch_soup(client, p["listing_url"])
        if soup:
            out.extend(_extract_from_soup(soup, _base_url(p["listing_url"]), p["name"], seen_urls))

    if js_portals:
        async with BrowserSession() as browser:
            if browser.available:
                for p in js_portals:
                    await polite_delay()
                    html = await browser.fetch(p["listing_url"])
                    if html:
                        soup = BeautifulSoup(html, "html.parser")
                        out.extend(_extract_from_soup(
                            soup, _base_url(p["listing_url"]), p["name"], seen_urls,
                        ))
    return out


# ─── SHARED HELPERS ──────────────────────────────────────────────────────────

def _try_assignment(
    title: str, description: str, location: str, url: str,
    source: str, seen_urls: set[str],
) -> Assignment | None:
    """Create an Assignment if it passes all filters."""
    if not title or len(title) < 5 or not url or url in seen_urls:
        return None
    if not is_relevant(title, description):
        return None
    if location and not is_in_stockholm(location):
        return None
    if not is_contract(title, description, source=source):
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


async def _fetch_soup(client: httpx.AsyncClient, url: str) -> BeautifulSoup | None:
    """Fetch a URL and return parsed HTML, or None on error."""
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except httpx.HTTPError:
        return None


def _strip_html(value: str) -> str:
    return clean_text(BeautifulSoup(value or "", "html.parser").get_text(" ", strip=True))


def _base_url(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _extract_location_from_text(text: str) -> str:
    """Try to extract a location from surrounding text."""
    text_lower = text.lower()
    for keyword in ["stockholm", "sthlm", "solna", "sundbyberg", "kista"]:
        if keyword in text_lower:
            return "Stockholm"
    if "remote" in text_lower or "distans" in text_lower:
        return "Remote"
    if "hybrid" in text_lower:
        return "Stockholm"
    return ""


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


# ─── DEDICATED HTML SCRAPERS ────────────────────────────────────────────────

async def _scrape_itc_network(
    client: httpx.AsyncClient, portal: dict, seen_urls: set[str],
) -> list[Assignment]:
    """ITC Network: assignments as h3 headings with metadata in parent text."""
    soup = await _fetch_soup(client, portal["url"])
    if not soup:
        return []
    out = []
    for h3 in soup.select("h3"):
        title = clean_text(h3.get_text())
        if not title or len(title) < 10 or title == "Öppna uppdrag":
            continue
        parent_text = clean_text(h3.parent.get_text()) if h3.parent else ""
        location = ""
        m = re.search(r"PLACERINGSORT:\s*(.+?)(?:SÖK|OMFATT|$)", parent_text)
        if m:
            location = clean_text(m.group(1))
        desc = ""
        dm = re.search(r"KOMPETENS:\s*(.+?)(?:PERIOD|$)", parent_text)
        if dm:
            desc = clean_text(dm.group(1))
        slug = re.sub(r"\W+", "-", title.lower())[:60]
        url = f"{portal['url']}#{slug}"
        a = _try_assignment(title, desc, location, url, "ITC Network", seen_urls)
        if a:
            out.append(a)
    return out


async def _scrape_konsultfabriken(
    client: httpx.AsyncClient, portal: dict, seen_urls: set[str],
) -> list[Assignment]:
    """Konsultfabriken: holographic cards with /assignments/ links."""
    soup = await _fetch_soup(client, portal["url"])
    if not soup:
        return []
    out = []
    for card in soup.select("li[class*='holographic']"):
        link = card.select_one("a[href*='/assignments/']")
        if not link:
            continue
        title = clean_text(link.get_text())
        href = link.get("href", "")
        url = urljoin(portal["url"], href)
        location = _extract_location_from_text(title)
        a = _try_assignment(title, "", location, url, "Konsultfabriken", seen_urls)
        if a:
            out.append(a)
    return out


async def _scrape_regent(
    client: httpx.AsyncClient, portal: dict, seen_urls: set[str],
) -> list[Assignment]:
    """Regent: assignment links matching /uppdrag/{id}."""
    soup = await _fetch_soup(client, portal["url"])
    if not soup:
        return []
    out = []
    for link in soup.select("a[href]"):
        href = link.get("href", "")
        if not re.search(r"/uppdrag/\d+", href):
            continue
        title = clean_text(link.get_text())
        if not title or title in ("Visa uppdraget", "Uppdrag"):
            continue
        url = urljoin("https://regent.se/", href)
        a = _try_assignment(title, "", "", url, "Regent", seen_urls)
        if a:
            out.append(a)
    return out


async def _scrape_nikita(
    client: httpx.AsyncClient, portal: dict, seen_urls: set[str],
) -> list[Assignment]:
    """Nikita: Odoo job listings with /jobs/detail/ links."""
    soup = await _fetch_soup(client, portal["url"])
    if not soup:
        return []
    out = []
    for link in soup.select("a[href*='/jobs/detail/']"):
        title = clean_text(link.get_text())
        # Strip date prefix like "28 May "
        title = re.sub(r"^\d{1,2}\s+\w+\s+", "", title)
        href = link.get("href", "")
        url = urljoin("https://www.nikita.se/", href)
        location = _extract_location_from_text(title)
        a = _try_assignment(title, "", location, url, "Nikita", seen_urls)
        if a:
            out.append(a)
    return out


async def _scrape_rpg(
    client: httpx.AsyncClient, portal: dict, seen_urls: set[str],
) -> list[Assignment]:
    """Right People Group: /open-assignments/ links with metadata in text."""
    soup = await _fetch_soup(client, portal["url"])
    if not soup:
        return []
    out = []
    for link in soup.select("a[href*='/open-assignments/']"):
        href = link.get("href", "")
        if href.rstrip("/").endswith("/open-assignments"):
            continue
        raw = clean_text(link.get_text())
        # Title ends at date pattern (2026.05.27) — everything after is metadata
        title = re.split(r"\s*\(\d{4}[\.\-]\d{2}[\.\-]\d{2}\)", raw)[0]
        title = clean_text(title)
        url = urljoin("https://rightpeoplegroup.com/", href)
        location = _extract_location_from_text(raw)
        a = _try_assignment(title, raw, location, url, "Right People Group", seen_urls)
        if a:
            out.append(a)
    return out


async def _scrape_profinder(
    client: httpx.AsyncClient, portal: dict, seen_urls: set[str],
) -> list[Assignment]:
    """Profinder: Wix blog with /post/ links."""
    soup = await _fetch_soup(client, portal["url"])
    if not soup:
        return []
    out = []
    for link in soup.select("a[href*='/post/']"):
        title = clean_text(link.get_text())
        if not title or len(title) < 10:
            continue
        href = link.get("href", "")
        url = urljoin("https://www.profinder.se/", href)
        location = _extract_location_from_text(title)
        a = _try_assignment(title, "", location, url, "Profinder", seen_urls)
        if a:
            out.append(a)
    return out


async def _scrape_tech_relations(
    client: httpx.AsyncClient, portal: dict, seen_urls: set[str],
) -> list[Assignment]:
    """Tech Relations: assignment cards with /konsultuppdrag/ links."""
    soup = await _fetch_soup(client, portal["url"])
    if not soup:
        return []
    out = []
    seen_titles: set[str] = set()
    for card in soup.select("[class*='assignment']"):
        link = card.select_one("a[href*='/konsultuppdrag/']")
        if not link:
            continue
        title = clean_text(link.get_text())
        if title in seen_titles or not title:
            continue
        seen_titles.add(title)
        href = link.get("href", "")
        url = urljoin("https://www.techrelations.se/", href)
        desc = clean_text(card.get_text())
        location = _extract_location_from_text(f"{title} {desc}")
        a = _try_assignment(title, desc, location, url, "Tech Relations", seen_urls)
        if a:
            out.append(a)
    return out


async def _scrape_interim_search(
    client: httpx.AsyncClient, portal: dict, seen_urls: set[str],
) -> list[Assignment]:
    """Interim Search: structured job cards with ID, title, company, location."""
    soup = await _fetch_soup(client, portal["url"])
    if not soup:
        return []
    out = []
    for card in soup.select(".jobs-list .card"):
        link = card.select_one("a[href]")
        if not link:
            continue
        title = clean_text(link.get_text())
        href = link.get("href", "")
        url = href if href.startswith("http") else urljoin("https://www.interimsearch.com/", href)
        location = ""
        for extra in card.select("li.extra-item"):
            text = clean_text(extra.get_text())
            if text.lower().startswith("ort:"):
                location = text[4:].strip()
        desc_el = card.select_one(".description")
        desc = clean_text(desc_el.get_text()) if desc_el else ""
        a = _try_assignment(title, desc, location, url, "Interim Search", seen_urls)
        if a:
            out.append(a)
    return out


async def _scrape_levigo(
    client: httpx.AsyncClient, portal: dict, seen_urls: set[str],
) -> list[Assignment]:
    """Levigo: direct links to assignment.levigo.se with title+location."""
    soup = await _fetch_soup(client, portal["url"])
    if not soup:
        return []
    out = []
    for link in soup.select("a[href*='assignment.levigo.se']"):
        title = clean_text(link.get_text())
        if not title or len(title) < 5:
            continue
        url = link.get("href", "")
        location = _extract_location_from_text(title)
        a = _try_assignment(title, "", location, url, "Levigo", seen_urls)
        if a:
            out.append(a)
    return out


async def _scrape_house_of_skills(
    client: httpx.AsyncClient, portal: dict, seen_urls: set[str],
) -> list[Assignment]:
    """House of Skills: WP blog articles for konsultuppdrag."""
    soup = await _fetch_soup(client, portal["url"])
    if not soup:
        return []
    out = []
    for article in soup.select("article"):
        link = article.select_one("h2 a, .entry-title a, h3 a, a[rel='bookmark']")
        if not link:
            continue
        title = clean_text(link.get_text())
        if not title or title.upper() == "KONSULTUPPDRAG":
            continue
        href = link.get("href", "")
        url = href if href.startswith("http") else urljoin(portal["url"], href)
        location = _extract_location_from_text(article.get_text())
        a = _try_assignment(title, "", location, url, "House of Skills", seen_urls)
        if a:
            out.append(a)
    return out


async def _scrape_wiseone(
    client: httpx.AsyncClient, portal: dict, seen_urls: set[str],
) -> list[Assignment]:
    """WiseOne: list items with assignmentId links, structured text."""
    soup = await _fetch_soup(client, portal["url"])
    if not soup:
        return []
    out = []
    for link in soup.select("a[href*='assignmentId']"):
        container = link.parent
        while container and container.name not in ("li", "div", "tr"):
            container = container.parent
        if not container:
            continue
        text = clean_text(container.get_text())
        # Format: "Title publiceringsdatum YYYY-MM-DD arbetsort Location Se uppdragsdetaljer"
        parts = text.split("publiceringsdatum")
        title = clean_text(parts[0]) if parts else ""
        location = ""
        loc_match = re.search(r"arbetsort\s+(.+?)(?:\s*Se uppdragsdetaljer|$)", text)
        if loc_match:
            location = clean_text(loc_match.group(1))
        href = link.get("href", "")
        url = urljoin("https://datakonsulter.info/WiseDki/", href)
        a = _try_assignment(title, "", location, url, "WiseOne", seen_urls)
        if a:
            out.append(a)
    return out


async def _scrape_brainville(
    client: httpx.AsyncClient, portal: dict, seen_urls: set[str],
) -> list[Assignment]:
    """Brainville: featured assignment cards on public listing page."""
    soup = await _fetch_soup(client, portal["url"])
    if not soup:
        return []
    out = []
    for card in soup.select("div.c_card"):
        link = card.select_one("a[href]")
        if not link:
            continue
        href = link.get("href", "")
        if not href or href == "#":
            continue
        text_el = card.select_one(".c_card__text")
        raw_text = clean_text(text_el.get_text()) if text_el else clean_text(card.get_text())
        title_el = card.select_one("strong, h3, h4, .c_card__title")
        title = clean_text(title_el.get_text()) if title_el else raw_text[:100]
        url = urljoin("https://www.brainville.com/", href)
        location = _extract_location_from_text(raw_text)
        a = _try_assignment(title, raw_text, location, url, "Brainville", seen_urls)
        if a:
            out.append(a)
    return out


async def _scrape_jappa(
    client: httpx.AsyncClient, portal: dict, seen_urls: set[str],
) -> list[Assignment]:
    """Jappa: TeamTailor-based with /jobb/{id} links."""
    soup = await _fetch_soup(client, portal["url"])
    if not soup:
        return []
    out = []
    for link in soup.select("a[href*='/jobb/']"):
        href = link.get("href", "")
        if not re.search(r"/jobb/\d+", href):
            continue
        title = clean_text(link.get_text())
        url = urljoin("https://www.jappa.jobs/", href)
        location = _extract_location_from_text(title)
        a = _try_assignment(title, "", location, url, "Jappa", seen_urls)
        if a:
            out.append(a)
    return out


async def _scrape_biolit(
    client: httpx.AsyncClient, portal: dict, seen_urls: set[str],
) -> list[Assignment]:
    """Biolit: konsultuppdrag page with assignment titles in mailto Subject."""
    soup = await _fetch_soup(client, BIOLIT_ASSIGNMENTS_URL)
    if not soup:
        return []
    out = []
    for link in soup.select("a[href^='mailto:']"):
        href = link.get("href", "")
        if "Subject=" not in href:
            continue
        subject = unquote(href.split("Subject=")[1].split("&")[0])
        title = clean_text(subject)
        if not title or len(title) < 5:
            continue
        slug = re.sub(r"\W+", "-", title.lower())[:60]
        url = f"{BIOLIT_ASSIGNMENTS_URL}#{slug}"
        location = _extract_location_from_text(title)
        a = _try_assignment(title, "", location, url, "Biolit", seen_urls)
        if a:
            out.append(a)
    return out


# ─── PORTAL SCRAPER DISPATCH ────────────────────────────────────────────────

_PORTAL_SCRAPERS = {
    "ITC Network": _scrape_itc_network,
    "Konsultfabriken": _scrape_konsultfabriken,
    "Regent": _scrape_regent,
    "Nikita": _scrape_nikita,
    "Right People Group": _scrape_rpg,
    "Profinder": _scrape_profinder,
    "Tech Relations": _scrape_tech_relations,
    "Interim Search": _scrape_interim_search,
    "Levigo": _scrape_levigo,
    "House of Skills": _scrape_house_of_skills,
    "WiseOne": _scrape_wiseone,
    "Brainville": _scrape_brainville,
    "Jappa": _scrape_jappa,
    "Biolit": _scrape_biolit,
}


# ─── GENERIC FALLBACK SCRAPER ───────────────────────────────────────────────

async def _scrape_generic_portal(
    client: httpx.AsyncClient, portal: dict, seen_urls: set[str],
) -> list[Assignment]:
    """Fallback: fetch a portal page over HTTP and extract assignments from it."""
    soup = await _fetch_soup(client, portal["url"])
    if not soup:
        return []
    return _extract_from_soup(soup, _base_url(portal["url"]), portal["name"], seen_urls)


def _extract_from_soup(
    soup: BeautifulSoup, base: str, name: str, seen_urls: set[str],
) -> list[Assignment]:
    """Extract assignments from already-parsed portal HTML (HTTP or rendered).

    Shared by the generic HTTP fallback, the discovery scanner, and the
    Playwright-rendered path so all three apply the same extraction strategies.
    """
    out: list[Assignment] = []

    # Strategy 1: Find structured cards/containers
    cards = soup.select(
        "article, .assignment, .uppdrag, .job-card, "
        "li.assignment-item, div[class*='card'], div[class*='Card'], "
        "div[class*='assignment'], div[class*='uppdrag'], "
        "div[class*='job'], div[class*='listing']"
    )
    if cards:
        for card in cards[:50]:
            assignment = _extract_from_card(card, base, name, seen_urls)
            if assignment:
                out.append(assignment)
        if out:
            return out

    # Strategy 2: Extract all links whose text matches keywords
    for link in soup.select("a[href]"):
        href = link.get("href", "")
        if not href or href.startswith("#") or href.startswith("mailto:"):
            continue
        link_text = clean_text(link.get_text())
        if not link_text or len(link_text) < 8 or len(link_text) > 200:
            continue
        if _is_navigation_link(link_text, href):
            continue
        parent = link.parent
        context = clean_text(parent.get_text()) if parent else ""
        url = href if href.startswith("http") else urljoin(base + "/", href)
        if not is_relevant(link_text, ""):
            continue
        location = _extract_location_from_text(context)
        if location and not is_in_stockholm(location):
            continue
        a = _try_assignment(
            link_text, context[:500] if context != link_text else "",
            location, url, name, seen_urls,
        )
        if a:
            out.append(a)

    # Strategy 3: Extract from headings
    if not out:
        for heading in soup.select("h2, h3"):
            title = clean_text(heading.get_text())
            if not title or len(title) < 8 or len(title) > 200:
                continue
            link_el = heading.find("a") or heading.find_parent("a")
            if not link_el:
                sibling = heading.find_next_sibling()
                if sibling:
                    link_el = sibling.find("a") if sibling.name != "a" else sibling
            href = link_el.get("href", "") if link_el else ""
            if not href:
                continue
            desc_el = heading.find_next_sibling()
            desc = clean_text(desc_el.get_text()) if desc_el else ""
            url = href if href.startswith("http") else urljoin(base + "/", href)
            location = _extract_location_from_text(f"{title} {desc}")
            if location and not is_in_stockholm(location):
                continue
            a = _try_assignment(title, desc, location, url, name, seen_urls)
            if a:
                out.append(a)

    return out


def _extract_from_card(card, base: str, source: str, seen_urls: set[str]) -> Assignment | None:
    """Extract an assignment from a structured card element."""
    title_el = card.select_one("h2, h3, h4, .title, strong, a")
    title = clean_text(title_el.get_text() if title_el else card.get_text()[:120])
    if not title or len(title) < 5:
        return None

    location_el = card.select_one(
        ".location, .city, .ort, [class*='location'], [class*='plats'], [class*='city']"
    )
    location = clean_text(location_el.get_text() if location_el else "")
    if not location:
        location = _extract_location_from_text(card.get_text())

    desc_el = card.select_one("p, .description, .summary, .excerpt, .ingress")
    description = clean_text(desc_el.get_text() if desc_el else "")

    href = card.get("href") or ""
    if not href:
        link_el = card.select_one("a[href]")
        href = link_el.get("href", "") if link_el else ""
    if not href:
        return None
    url = href if href.startswith("http") else urljoin(base + "/", href)

    return _try_assignment(title, description, location, url, source, seen_urls)


def _is_navigation_link(text: str, href: str) -> bool:
    """Return True if a link looks like site navigation rather than an assignment."""
    nav_words = {
        "hem", "home", "kontakt", "contact", "om oss", "about",
        "logga in", "login", "registrera", "register", "cookie",
        "integritetspolicy", "privacy", "villkor", "terms",
        "linkedin", "facebook", "instagram", "twitter",
        "nyhetsbrev", "newsletter", "visa fler", "load more",
        "nästa", "next", "föregående", "previous", "prenumerera",
        "tjänster", "services", "lösningar", "solutions",
        "karriär", "career", "careers", "nyheter", "news",
        "blogg", "blog", "partners", "kunder", "clients",
        "se uppdragsdetaljer", "läs mer", "read more",
        "meny", "menu", "sök", "search", "filter",
    }
    lower = text.lower()
    if any(w == lower or lower.startswith(w + " ") for w in nav_words):
        return True
    if len(text) < 4:
        return True
    if "logotype" in lower or "logo" in lower:
        return True
    return False
