"""Shared scraper utilities."""

import asyncio
import re
import httpx
from src.config import (
    KEYWORDS, LOCATION_KEYWORDS, REQUEST_TIMEOUT, SCRAPE_DELAY,
    CONTRACT_KEYWORDS, PERMANENT_KEYWORDS, PLAYWRIGHT_TIMEOUT_MS,
)


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "sv-SE,sv;q=0.9,en;q=0.8",
}


def make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers=HEADERS,
        timeout=REQUEST_TIMEOUT,
        follow_redirects=True,
    )


class BrowserSession:
    """Reusable headless-chromium session for rendering JS-heavy portals.

    Keeps one browser open across many fetches (discovery scans ~130 sites).
    Playwright is imported lazily so the rest of the pipeline works without it.

        async with BrowserSession() as browser:
            html = await browser.fetch(url)
    """

    def __init__(self) -> None:
        self._pw = None
        self._browser = None

    async def __aenter__(self) -> "BrowserSession":
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            print("[playwright] not installed — run 'python -m playwright install chromium'")
            return self
        try:
            self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.launch(headless=True)
        except Exception as e:
            print(f"[playwright] launch failed: {type(e).__name__}: {e}")
            self._browser = None
        return self

    async def __aexit__(self, *exc) -> None:
        try:
            if self._browser:
                await self._browser.close()
            if self._pw:
                await self._pw.stop()
        except Exception:
            pass

    @property
    def available(self) -> bool:
        return self._browser is not None

    async def fetch(self, url: str) -> str | None:
        """Render a URL and return its HTML, or None on failure."""
        if not self._browser:
            return None
        context = None
        try:
            context = await self._browser.new_context(
                user_agent=HEADERS["User-Agent"],
                locale="sv-SE",
            )
            page = await context.new_page()
            await page.goto(url, wait_until="networkidle", timeout=PLAYWRIGHT_TIMEOUT_MS)
            return await page.content()
        except Exception as e:
            print(f"[playwright] fetch failed for {url}: {type(e).__name__}")
            return None
        finally:
            if context:
                await context.close()


async def fetch_rendered(url: str) -> str | None:
    """One-shot render of a single URL (launches and closes a browser)."""
    async with BrowserSession() as browser:
        if not browser.available:
            return None
        return await browser.fetch(url)


def is_relevant(title: str, description: str = "") -> bool:
    """Return True if title or description contains at least one keyword."""
    text = (title + " " + description).lower()
    return any(kw.lower() in text for kw in KEYWORDS)


def has_contract_signal(title: str, description: str = "") -> bool:
    """Return True if text contains explicit freelance/contract wording."""
    text = (title + " " + description).lower()
    return any(kw in text for kw in CONTRACT_KEYWORDS)


def is_contract(title: str, description: str = "", source: str = "", broker: bool = False) -> bool:
    """Return True if the listing looks like a freelance/contract assignment.

    Broker portals (Ework, Brainville, etc.) are assumed to list contracts,
    so they pass by default unless they explicitly look like permanent jobs.
    Pass broker=True for assignments scraped from a broker portal (covers
    newly discovered portals that aren't in the hardcoded set below).
    For general job boards (Platsbanken, Indeed, LinkedIn), we require
    explicit contract wording and reject permanent-job signals.
    """
    text = (title + " " + description).lower()
    has_contract = has_contract_signal(title, description)
    has_permanent = any(kw in text for kw in PERMANENT_KEYWORDS)

    # Broker sources are mostly contracts, but still reject clear permanent listings.
    broker_sources = {
        "Ework", "Brainville", "Tingent", "Nikita", "Nox Consulting",
        "KeyMan", "Upgraded People", "Emagine", "Onsiter", "A Society",
        "Developers Bay", "Pro4u", "Senterprise", "ITC Network", "Regent",
        "Konsultkompaniet", "Aptitud", "Epico", "Right People Group",
        "Aliant", "MeOne", "Brightmill", "Cinode Market",
        "Afry", "Alphadev", "Biolit", "Donald Davis & Partners",
        "House of Skills", "Interim Search", "Jappa", "Konsultfabriken",
        "Konsultkooperativet", "Levigo", "Paventia", "Profinder",
        "Randstad", "Resursbrist", "Seequaly", "Sigma",
        "Tech Relations", "Wetal", "GetWiser", "WiseOne",
    }
    if broker or source in broker_sources:
        return not (has_permanent and not has_contract)

    # General job boards must explicitly indicate contract/freelance.
    if has_permanent:
        return False
    if has_contract:
        return True

    return False


def is_in_stockholm(location: str) -> bool:
    """Return True if location matches Stockholm area or remote."""
    loc = location.lower()
    return any(k in loc for k in LOCATION_KEYWORDS)


def clean_text(text: str) -> str:
    """Strip excess whitespace."""
    return re.sub(r"\s+", " ", text).strip()


async def polite_delay() -> None:
    await asyncio.sleep(SCRAPE_DELAY)
