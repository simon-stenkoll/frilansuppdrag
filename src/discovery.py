"""Deep discovery of Swedish consultant-broker assignment portals.

Reads Anna Leijon's curated broker list, then digs into each broker's site to
find a page that actually lists assignments. The result is written to
state/portals.json, which records the portals that show assignments.

A candidate page is judged by the same LLM extraction the nightly run uses
(src/scrapers/portal_llm.py): if the model can pull at least one assignment out of
the page, the portal works. The cheap listing_score heuristic is kept as a free
pre-filter so only pages with listing signals cost an LLM call.

Run occasionally / manually. It is heavy (renders ~130 sites with a browser):

    python -m src.discovery              # full deep discovery → state/portals.json
    python -m src.discovery --limit 10   # only the first 10 brokers (test runs)
    python -m src.discovery --probe      # quick HTTP status check of candidates
"""

import asyncio
import json
import os
import re
import sys
from datetime import date
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from openai import AuthenticationError, PermissionDeniedError

from src.classifier import LlmBudget, _client
from src.config import (
    LEIJON_URL,
    PORTALS_STATE_FILE,
    DISCOVERY_IT_KEYWORDS,
    ASSIGNMENT_NAV_KEYWORDS,
    DISCOVERY_LLM_BUDGET,
    DISCOVERY_MAX_LISTING_LINKS,
    DISCOVERY_CONCURRENCY,
    LLM_REQUEST_DELAY,
)
from src.scrapers.utils import make_client, BrowserSession, clean_text, polite_delay
from src.scrapers.portal_llm import extract_listings_llm, reduce_html, validate_items


# ─── ANNA LEIJON BROKER LIST ─────────────────────────────────────────────────

# Registry/social domains that are never assignment portals.
_NON_PORTAL_DOMAINS = (
    "annaleijon", "linkedin.", "facebook.", "twitter.", "instagram.",
    "allabolag.", "ratsit.", "google.com/maps", "youtube.",
)


def _is_external(href: str) -> bool:
    href = (href or "").lower()
    if not href.startswith("http"):
        return False
    return not any(s in href for s in _NON_PORTAL_DOMAINS)


def _norm_header(text: str) -> str:
    return re.sub(r"[^a-z]", "", (text or "").lower())


def _cell_link(cell) -> str:
    """First external link in a cell, or empty string."""
    if cell is None:
        return ""
    for a in cell.find_all("a"):
        href = a.get("href", "").strip()
        if _is_external(href):
            return href
    return ""


def extract_brokers(html: str) -> list[dict]:
    """Parse the broker tables into {name, website, uppdragsportal, sector}.

    Uses the table header row to locate the 'Uppdrags-portal' column rather than
    guessing, so the 'Om bolaget' (allabolag.se) column is never mistaken for it.
    """
    soup = BeautifulSoup(html, "html.parser")
    brokers: list[dict] = []
    seen: set[str] = set()

    for table in soup.select("table"):
        headers = [_norm_header(th.get_text()) for th in table.select("tr th")]
        portal_idx = next((i for i, h in enumerate(headers) if "uppdragsportal" in h), None)
        sector_idx = next((i for i, h in enumerate(headers) if "bransch" in h), 1)

        for row in table.select("tr"):
            cells = row.select("td")
            if len(cells) < 2:
                continue

            # Name + homepage come from the first cell's link (Namn column).
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

            # Uppdrags-portal column (by header index); empty for many brokers.
            uppdragsportal = ""
            if portal_idx is not None and portal_idx < len(cells):
                uppdragsportal = _cell_link(cells[portal_idx])

            if not website and not uppdragsportal:
                continue
            seen.add(key)

            sector = clean_text(cells[sector_idx].get_text()) if sector_idx < len(cells) else ""
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

# Minimum listing_score for a page with zero extracted items to count as "listing".
LISTING_STATUS_MIN_SCORE = 3
# Shortest reduced page worth spending an LLM call on.
MIN_REDUCED_CHARS = 80


def _base_url(url: str) -> str:
    """Scheme and host of a URL, used to resolve relative links."""
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


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
    _LISTING_FRAGMENTS = (
        "/uppdrag", "/assignment", "/jobb/", "/jobs/", "/job/", "assignmentid",
        "/lediga", "/consultant", "/opportunit", "/career", "/position",
        "/tjanst", "recman", "teamtailor", "/vacanc", "?assignment", "?job",
    )
    count = 0
    for a in soup.select("a[href]"):
        href = (a.get("href") or "").lower()
        if any(s in href for s in _LISTING_FRAGMENTS):
            count += 1
    return count


async def _http_html(client: httpx.AsyncClient, url: str) -> str | None:
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.text or ""
    except httpx.HTTPError:
        return None


async def _render_html(browser: BrowserSession, url: str) -> str | None:
    return await browser.fetch(url)


class LlmProbe:
    """Judges a candidate page with the nightly run's LLM extraction.

    The calls are serialised behind one lock (the OpenAI SDK is synchronous and
    the Gemini free tier rate limits hard), share one LlmBudget and stop for the
    rest of the run as soon as the budget, the key or the model itself gives out.
    """

    def __init__(self, budget: LlmBudget) -> None:
        self.budget = budget
        self.client = _client()
        self.disabled = self.client is None
        self.calls = 0
        self.deferred = 0
        self._lock = asyncio.Lock()
        if self.client is None:
            print("[discovery] GEMINI_API_KEY saknas: kör bara den "
                  "billiga heuristiken, portaler som kräver LLM-probe behåller sin "
                  "tidigare status\n")

    async def run(self, name: str, html: str, url: str) -> int | None:
        """Validated items on the page, or None when no call could be made."""
        if self.disabled:
            self.deferred += 1
            return None

        reduced = reduce_html(html, url)
        if len(reduced) < MIN_REDUCED_CHARS:
            print(f"[discovery] {name}: sidan gav för lite text för LLM-probe ({url})")
            return 0

        async with self._lock:
            if self.disabled:  # another worker drained the budget while we waited
                self.deferred += 1
                return None
            if not self.budget.spend():
                self.disabled = True
                self.deferred += 1
                print(f"[discovery] LLM-budgeten ({self.budget.limit} anrop) är slut, "
                      "resterande portaler behåller sin tidigare status")
                return None
            if self.calls:
                await asyncio.sleep(LLM_REQUEST_DELAY)
            self.calls += 1
            try:
                raw_items = await asyncio.to_thread(
                    extract_listings_llm, self.client, name, reduced,
                )
            except (AuthenticationError, PermissionDeniedError) as e:
                self.disabled = True
                self.deferred += 1
                print(f"[discovery] LLM-probe avbruten, auth-fel: {type(e).__name__}: {e}")
                return None
            except Exception as e:
                self.deferred += 1
                print(f"[discovery] {name}: LLM-probe misslyckades: {type(e).__name__}: {e}")
                return None

        items = validate_items(raw_items, url, name)
        print(f"[discovery] {name}: LLM-probe gav {len(raw_items)} items, "
              f"{len(items)} validerade ({url})")
        return len(items)


async def investigate(
    broker: dict, client: httpx.AsyncClient, browser: BrowserSession, probe: LlmProbe,
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
    llm_zero = False
    deferred = False

    async def consider(soup: BeautifulSoup, html: str, url: str, method: str) -> bool:
        """Update record from a fetched page; return True if 'working'."""
        nonlocal reached, best_listing, llm_zero, deferred
        reached = True
        listing = _listing_score(soup)
        if listing > best_listing:
            best_listing = listing
            record.update(listing_url=url, method=method, listing_score=listing)
        if listing <= 0:
            return False  # no listing signals: not worth an LLM call

        found = await probe.run(name, html, url)
        if found is None:
            deferred = True
            return False
        if found >= 1:
            record.update(
                listing_url=url, method=method, status="working",
                relevant_count=found, listing_score=listing,
                last_found=date.today().isoformat(),
            )
            return True
        llm_zero = True
        return False

    for url in candidates:
        # Try HTTP first (cheap), then escalate to a rendered browser page.
        for method, fetch in (("http", lambda u: _http_html(client, u)),
                              ("playwright", lambda u: _render_html(browser, u))):
            if method == "playwright" and not browser.available:
                continue
            html = await fetch(url)
            if not html:
                continue
            soup = BeautifulSoup(html, "html.parser")
            if await consider(soup, html, url, method):
                return record
            # Follow listing-page links discovered on this page.
            for link in _find_listing_links(soup, _base_url(url)):
                sub_html = await fetch(link)
                if not sub_html:
                    continue
                if await consider(BeautifulSoup(sub_html, "html.parser"), sub_html,
                                  link, method):
                    return record
                await polite_delay()

    if not reached:
        print(f"[discovery] {name}: empty, ingen sida kunde hämtas (hämtningsfel)")
    elif deferred:
        # Budget or token ran out: the previous status is restored after the run.
        record["status"] = "deferred"
    elif llm_zero:
        record["status"] = "listing" if best_listing >= LISTING_STATUS_MIN_SCORE else "empty"
        if record["status"] == "empty":
            print(f"[discovery] {name}: empty, LLM:en extraherade 0 uppdrag")
    else:
        record["status"] = "empty"
        print(f"[discovery] {name}: empty, ingen kandidatsida med listningssignaler")
    return record


# ─── ORCHESTRATION ───────────────────────────────────────────────────────────

async def run_discovery(limit: int = 0) -> list[dict]:
    print("=== Broker portal discovery ===")
    previous = _load_previous_portals()
    async with make_client() as client:
        try:
            resp = await client.get(LEIJON_URL)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            print(f"Failed to fetch Anna Leijon list: {e}")
            return []

        brokers = filter_it_brokers(extract_brokers(resp.text))
        print(f"Found {len(brokers)} IT-relevant brokers with links")
        if limit > 0:
            brokers = brokers[:limit]
            print(f"--limit {limit}: bearbetar {len(brokers)} av dem")
        print()

        probe = LlmProbe(LlmBudget(limit=DISCOVERY_LLM_BUDGET))
        results: list[dict] = []
        sem = asyncio.Semaphore(DISCOVERY_CONCURRENCY)

        async with BrowserSession() as browser:
            if not browser.available:
                print("[discovery] Playwright unavailable, HTTP-only (JS portals will be missed)\n")

            async def worker(b: dict) -> None:
                async with sem:
                    rec = await investigate(b, client, browser, probe)
                    flag = {"working": "OK", "listing": "..", "empty": "  ",
                            "error": "XX", "deferred": ">>"}.get(rec["status"], "??")
                    print(f"  [{flag}] {rec['name'][:32]:32s} {rec['status']:8s} "
                          f"rel={rec['relevant_count']} {rec['listing_url']}")
                    results.append(rec)

            await asyncio.gather(*(worker(b) for b in brokers))

    deferred = _restore_deferred(results, previous)
    results.sort(key=lambda r: (r["status"] != "working", r["status"] != "listing", r["name"].lower()))
    _save_portals(results)

    working = sum(1 for r in results if r["status"] == "working")
    listing = sum(1 for r in results if r["status"] == "listing")
    print(f"\n=== Done: {working} working, {listing} listing, {len(results)} total, "
          f"{probe.calls} LLM-anrop, {deferred} uppskjutna → {PORTALS_STATE_FILE} ===")
    return results


def _restore_deferred(results: list[dict], previous: dict[str, dict]) -> int:
    """Give portals that never got their LLM probe their previous status back.

    A drained budget (or a missing token) must never demote a working portal to
    "empty"; without a previous record the cheap heuristic decides instead.
    """
    count = 0
    for r in results:
        if r["status"] != "deferred":
            continue
        count += 1
        prev = previous.get(r["name"])
        if prev:
            r["status"] = prev.get("status", "empty")
            r["listing_url"] = r["listing_url"] or prev.get("listing_url", "")
            r["method"] = prev.get("method", r["method"])
            r["relevant_count"] = prev.get("relevant_count", 0)
        else:
            r["status"] = ("listing" if r["listing_score"] >= LISTING_STATUS_MIN_SCORE
                           else "empty")
    if count:
        print(f"\n[discovery] {count} portaler fick ingen LLM-probe (budget slut eller "
              "token saknas) och behåller sin tidigare status")
    return count


def _load_previous_portals() -> dict[str, dict]:
    """Records from the portals.json of the previous run, keyed by broker name."""
    previous: dict[str, dict] = {}
    if os.path.exists(PORTALS_STATE_FILE):
        try:
            with open(PORTALS_STATE_FILE, "r", encoding="utf-8") as f:
                for p in json.load(f).get("portals", []):
                    previous[p.get("name")] = p
        except (OSError, json.JSONDecodeError, AttributeError):
            previous = {}
    return previous


def _save_portals(results: list[dict]) -> None:
    """Write portals.json, preserving previous last_found where newer data is empty."""
    previous = _load_previous_portals()

    for r in results:
        if not r["last_found"] and r["name"] in previous:
            r["last_found"] = previous[r["name"]].get("last_found", "")

    os.makedirs(os.path.dirname(PORTALS_STATE_FILE), exist_ok=True)
    with open(PORTALS_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"generated": date.today().isoformat(), "portals": results}, f,
                  ensure_ascii=False, indent=2)


async def probe(limit: int = 0) -> None:
    """Quick HTTP status check of every broker candidate URL (no deep crawl)."""
    async with make_client() as client:
        resp = await client.get(LEIJON_URL)
        brokers = filter_it_brokers(extract_brokers(resp.text))
        if limit > 0:
            brokers = brokers[:limit]
        print(f"Probing {len(brokers)} brokers\n")
        for b in brokers:
            url = b.get("uppdragsportal") or b.get("website")
            try:
                r = await client.get(url)
                print(f"  {r.status_code}  {b['name'][:32]:32s}  {url}")
            except httpx.HTTPError as e:
                print(f"  ERR  {b['name'][:32]:32s}  {type(e).__name__}")


def _arg_int(argv: list[str], flag: str, default: int = 0) -> int:
    """Read an integer CLI flag written as '--flag N' or '--flag=N'."""
    for i, arg in enumerate(argv):
        value = ""
        if arg == flag and i + 1 < len(argv):
            value = argv[i + 1]
        elif arg.startswith(flag + "="):
            value = arg.split("=", 1)[1]
        if value:
            try:
                return int(value)
            except ValueError:
                print(f"[discovery] ogiltigt värde för {flag}: {value!r}")
    return default


if __name__ == "__main__":
    try:  # ensure non-ASCII (åäö, broker names) print on a Windows console
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    max_brokers = _arg_int(sys.argv, "--limit")
    if "--probe" in sys.argv:
        asyncio.run(probe(max_brokers))
    else:
        asyncio.run(run_discovery(max_brokers))
