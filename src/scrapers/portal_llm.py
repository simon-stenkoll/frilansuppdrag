"""LLM extraction of assignment listings from Swedish broker portals.

Replaces the hand written HTML parsers: every portal page found by discovery is
fetched, reduced to LLM friendly text and handed to one chat completion that returns
the listings as JSON. A page hash cache in state/portal_pages.json means an unchanged
listing page costs no LLM call at all.

Budget: this module competes for the same LlmBudget as the classifier. Since scrapers
run before classify() in main.py, main.py owns the budget instance and hands it over
with set_budget() before the run. The scraper interface stays `async def scrape()`.
"""

import asyncio
import hashlib
import json
import os
from datetime import date
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from openai import AuthenticationError, OpenAI, PermissionDeniedError

# _client() is reused verbatim so both LLM consumers authenticate identically.
from src.classifier import LlmBudget, _client
from src.config import (
    DISABLED_BROKER_PORTALS,
    LLM_MODEL,
    LLM_REQUEST_DELAY,
    PORTAL_ATS_DOMAINS,
    PORTAL_LLM_MAX_CALLS,
    PORTAL_PAGES_STATE_FILE,
    PORTAL_TEXT_MAX_CHARS,
    PORTALS_STATE_FILE,
)
from src.models import Assignment
from src.scrapers.utils import (
    BrowserSession,
    clean_text,
    is_relevant,
    make_client,
    polite_delay,
)

SOURCE_LABEL = "portal-llm"

# Portal statuses from discovery that are worth fetching again.
ACTIVE_PORTAL_STATUSES = ("working", "listing")

# Structural tags that never carry assignment text.
STRIP_TAGS = ["script", "style", "nav", "footer", "header", "noscript", "svg", "form"]

# Public suffixes with two labels, needed to compare registrable domains correctly.
_MULTI_LABEL_SUFFIXES = {
    "co.uk", "org.uk", "ac.uk", "com.au", "net.au", "co.nz", "com.br", "co.jp",
}

# Shortest reduced page worth spending an LLM call on.
_MIN_REDUCED_CHARS = 80

# Set by main.py before the run so portal extraction and classify() share one counter.
BUDGET: LlmBudget | None = None


def set_budget(budget: LlmBudget | None) -> None:
    """Hand this module the pipeline's shared LLM budget."""
    global BUDGET
    BUDGET = budget


# ─── PORTAL LIST ─────────────────────────────────────────────────────────────

def load_portals() -> list[dict]:
    """Active portals from state/portals.json: status working/listing with a listing_url."""
    if not os.path.exists(PORTALS_STATE_FILE):
        print(f"[{SOURCE_LABEL}] {PORTALS_STATE_FILE} saknas, kör src.discovery först")
        return []
    try:
        with open(PORTALS_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        portals = data.get("portals") if isinstance(data, dict) else data
        if not isinstance(portals, list):
            raise ValueError("portals is not a list")
    except Exception as e:
        print(f"[{SOURCE_LABEL}] kunde inte läsa {PORTALS_STATE_FILE}: {type(e).__name__}: {e}")
        return []

    active: list[dict] = []
    for p in portals:
        if not isinstance(p, dict):
            continue
        if p.get("status") not in ACTIVE_PORTAL_STATUSES:
            continue
        if not clean_text(p.get("listing_url") or ""):
            continue
        if p.get("name") in DISABLED_BROKER_PORTALS:
            continue
        active.append(p)
    return active


# ─── HTML REDUCTION ──────────────────────────────────────────────────────────

def reduce_html(html: str, base_url: str) -> str:
    """Strip a listing page down to plain text with markdown style absolute links."""
    soup = BeautifulSoup(html or "", "html.parser")

    for tag in soup.find_all(STRIP_TAGS):
        tag.decompose()

    for a in soup.find_all("a"):
        href = a.get("href")
        if not href:
            continue
        text = clean_text(a.get_text(" ", strip=True))
        a.replace_with(f"[{text}]({urljoin(base_url, href)})")

    lines: list[str] = []
    letter_run: list[str] = []
    for raw_line in soup.get_text("\n").splitlines():
        line = clean_text(raw_line)
        if not line:
            continue
        # Some portals animate a heading with one span per character, which would
        # otherwise turn into hundreds of one letter lines and eat the whole budget.
        if len(line) == 1:
            letter_run.append(line)
            continue
        if letter_run:
            lines.append("".join(letter_run))
            letter_run = []
        lines.append(line)
    if letter_run:
        lines.append("".join(letter_run))
    return "\n".join(lines)[:PORTAL_TEXT_MAX_CHARS]


def page_hash(reduced_text: str) -> str:
    """Fingerprint the reduced page so an unchanged portal costs no LLM call."""
    return hashlib.sha1((reduced_text or "").encode("utf-8")).hexdigest()


# ─── ITEM VALIDATION ─────────────────────────────────────────────────────────

def registrable_domain(url: str) -> str:
    """Registrable domain of a URL, for example 'sub.keyman.se' -> 'keyman.se'."""
    host = (urlparse(url or "").hostname or "").lower().strip(".")
    parts = [p for p in host.split(".") if p]
    if len(parts) < 2:
        return host
    if len(parts) >= 3 and ".".join(parts[-2:]) in _MULTI_LABEL_SUFFIXES:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _domain_allowed(url: str, listing_url: str) -> bool:
    domain = registrable_domain(url)
    if not domain:
        return False
    if domain == registrable_domain(listing_url):
        return True
    return domain in PORTAL_ATS_DOMAINS


def validate_items(raw_items, listing_url: str, portal_name: str = "") -> list[dict]:
    """Keep the items with a plausible title and a link on an allowed domain."""
    out: list[dict] = []
    if not isinstance(raw_items, list):
        return out

    seen: set[str] = set()
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        title = clean_text(str(item.get("title") or ""))
        url = clean_text(str(item.get("url") or ""))

        if len(title) <= 3:
            print(f"[{SOURCE_LABEL}] {portal_name}: kastar item med för kort titel '{title}'")
            continue
        if not url.lower().startswith("http"):
            print(f"[{SOURCE_LABEL}] {portal_name}: kastar '{title[:50]}', "
                  f"ogiltig url '{url[:60]}'")
            continue
        if not _domain_allowed(url, listing_url):
            print(f"[{SOURCE_LABEL}] {portal_name}: kastar '{title[:50]}', "
                  f"främmande domän {registrable_domain(url)}")
            continue
        if url in seen:
            continue

        seen.add(url)
        out.append({
            "title": title[:150],
            "company": clean_text(str(item.get("company") or ""))[:120],
            "location": clean_text(str(item.get("location") or ""))[:120],
            "url": url,
            "snippet": clean_text(str(item.get("snippet") or ""))[:500],
        })
    return out


# ─── PAGE CACHE ──────────────────────────────────────────────────────────────

def load_page_cache() -> dict[str, dict]:
    if not os.path.exists(PORTAL_PAGES_STATE_FILE):
        return {}
    try:
        with open(PORTAL_PAGES_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"[{SOURCE_LABEL}] kunde inte läsa {PORTAL_PAGES_STATE_FILE}: {type(e).__name__}")
        return {}


def save_page_cache(cache: dict[str, dict], active_urls) -> None:
    """Write the cache, dropping entries for portals that are no longer active."""
    keep = set(active_urls or [])
    pruned = {url: entry for url, entry in cache.items() if url in keep}
    os.makedirs(os.path.dirname(PORTAL_PAGES_STATE_FILE) or ".", exist_ok=True)
    with open(PORTAL_PAGES_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(pruned, f, indent=2, ensure_ascii=False, sort_keys=True)


def cache_entry(hash_value: str, items: list[dict]) -> dict:
    return {"page_hash": hash_value, "checked": date.today().isoformat(), "items": items}


# ─── LLM EXTRACTION ──────────────────────────────────────────────────────────

def build_prompt(portal_name: str, reduced_text: str) -> str:
    """Prompt for one portal listing page."""
    return (
        "The text below is a reduced version of a web page from a Swedish consultant "
        f"broker named '{portal_name}'. Links appear as [link text](absolute url).\n\n"
        "Extract EVERY individual consultant assignment or job listed on the page. "
        "Answer ONLY with valid JSON, no markdown fences, no commentary, in this shape:\n"
        '{"items": [{"title": "", "company": "", "location": "", "url": "", "snippet": ""}]}\n\n'
        "Rules:\n"
        "- Ignore navigation, menus, news articles, blog posts, employee profiles, "
        "call to action links (for example 'kontakta oss', 'registrera CV', 'läs mer om oss') "
        "and descriptions of the broker's own services.\n"
        "- If the page does not list any assignments, return {\"items\": []}.\n"
        "- company, location and snippet may be empty strings when the page does not say. "
        "Never guess them.\n"
        "- url must be the absolute link to that specific assignment, copied exactly from "
        "the text. NEVER invent a URL that does not appear in the text. Skip an assignment "
        "that has no link.\n"
        "- title is the assignment title as written on the page.\n"
        "- snippet is a short excerpt from the page about that assignment, at most 300 "
        "characters, copied from the text.\n\n"
        f"Page text:\n{reduced_text}"
    )


def extract_listings_llm(client: OpenAI, portal_name: str, reduced_text: str) -> list[dict]:
    """One chat completion per page. Returns the raw, unvalidated items."""
    resp = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[{"role": "user", "content": build_prompt(portal_name, reduced_text)}],
        max_tokens=1500,
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    raw = (resp.choices[0].message.content or "").strip()
    # Some models wrap the JSON in markdown fences despite response_format.
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        data = json.loads(raw)
    except Exception:
        print(f"[{SOURCE_LABEL}] {portal_name}: modellen svarade inte med giltig JSON")
        return []
    if not isinstance(data, dict):
        return []
    items = data.get("items")
    return items if isinstance(items, list) else []


# ─── FETCHING ────────────────────────────────────────────────────────────────

async def _fetch_http(client: httpx.AsyncClient, url: str) -> str:
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.text or ""
    except httpx.HTTPError as e:
        print(f"[{SOURCE_LABEL}] http misslyckades för {url}: {type(e).__name__}")
        return ""


# ─── MAIN ENTRY POINT ────────────────────────────────────────────────────────

async def scrape() -> list[Assignment]:
    portals = load_portals()
    if not portals:
        return []

    cache = load_page_cache()
    llm = _client()
    if llm is None:
        print(f"[{SOURCE_LABEL}] GEMINI_API_KEY saknas, kör bara sidcachen")

    budget = BUDGET if BUDGET is not None else LlmBudget()
    browser: BrowserSession | None = None

    async def get_browser() -> BrowserSession | None:
        """Launch the headless browser on first need, never for an all-http run."""
        nonlocal browser
        if browser is None:
            browser = await BrowserSession().__aenter__()
        return browser if browser.available else None

    results: list[Assignment] = []
    seen_urls: set[str] = set()
    active_urls: list[str] = []
    cached_pages = llm_pages = deferred_pages = failed_pages = 0
    filtered_out = 0
    calls_made = 0
    llm_disabled = llm is None

    try:
        async with make_client() as http_client:
            for portal in portals:
                name = clean_text(portal.get("name") or "Okänd portal")
                listing_url = clean_text(portal.get("listing_url") or "")
                active_urls.append(listing_url)
                try:
                    await polite_delay()

                    html = ""
                    if portal.get("method") != "playwright":
                        html = await _fetch_http(http_client, listing_url)
                    if not html.strip():
                        session = await get_browser()
                        if session is not None:
                            html = await session.fetch(listing_url) or ""
                    if not html.strip():
                        failed_pages += 1
                        print(f"[{SOURCE_LABEL}] {name}: ingen HTML hämtad")
                        continue

                    reduced = reduce_html(html, listing_url)
                    if len(reduced) < _MIN_REDUCED_CHARS:
                        failed_pages += 1
                        print(f"[{SOURCE_LABEL}] {name}: sidan gav för lite text")
                        continue

                    hash_value = page_hash(reduced)
                    entry = cache.get(listing_url)
                    if isinstance(entry, dict) and entry.get("page_hash") == hash_value:
                        items = [i for i in (entry.get("items") or []) if isinstance(i, dict)]
                        cached_pages += 1
                    else:
                        if llm_disabled:
                            deferred_pages += 1
                            continue
                        if calls_made >= PORTAL_LLM_MAX_CALLS:
                            llm_disabled = True
                            deferred_pages += 1
                            print(f"[{SOURCE_LABEL}] modultaket ({PORTAL_LLM_MAX_CALLS} anrop) "
                                  "nått, resterande portaler väntar till nästa körning")
                            continue
                        if not budget.spend():
                            llm_disabled = True
                            deferred_pages += 1
                            print(f"[{SOURCE_LABEL}] den delade LLM-budgeten "
                                  f"({budget.limit} anrop) är slut")
                            continue

                        if calls_made:
                            await asyncio.sleep(LLM_REQUEST_DELAY)
                        calls_made += 1
                        try:
                            raw_items = extract_listings_llm(llm, name, reduced)
                        except (AuthenticationError, PermissionDeniedError) as e:
                            llm_disabled = True
                            deferred_pages += 1
                            print(f"[{SOURCE_LABEL}] ABORTED, auth-fel: {type(e).__name__}: {e}")
                            continue
                        items = validate_items(raw_items, listing_url, name)
                        cache[listing_url] = cache_entry(hash_value, items)
                        llm_pages += 1

                    for item in items:
                        url = item.get("url", "")
                        if not url or url in seen_urls:
                            continue
                        if not is_relevant(item.get("title", ""), item.get("snippet", "")):
                            filtered_out += 1
                            continue
                        seen_urls.add(url)
                        results.append(Assignment(
                            title=item.get("title", ""),
                            company=item.get("company", "") or f"(via {name})",
                            location=item.get("location", "") or "Sweden",
                            description=item.get("snippet", ""),
                            url=url,
                            source=name,
                        ))
                except Exception as e:
                    failed_pages += 1
                    print(f"[{SOURCE_LABEL}] {name} FAILED: {type(e).__name__}: {e}")
    finally:
        if browser is not None:
            await browser.__aexit__(None, None, None)

    save_page_cache(cache, active_urls)
    print(f"[{SOURCE_LABEL}] {len(portals)} portaler: {llm_pages} via LLM, "
          f"{cached_pages} från sidcache, {deferred_pages} uppskjutna, "
          f"{failed_pages} misslyckade (budget {budget.used}/{budget.limit})")
    print(f"[{SOURCE_LABEL}] {len(results)} uppdrag kvar efter nyckelordsfilter, "
          f"{filtered_out} bortfiltrerade")
    return results
