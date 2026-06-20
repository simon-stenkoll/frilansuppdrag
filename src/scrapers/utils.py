"""Shared scraper utilities."""

import asyncio
import re
import httpx
from src.config import KEYWORDS, LOCATION_KEYWORDS, REQUEST_TIMEOUT, SCRAPE_DELAY, CONTRACT_KEYWORDS, PERMANENT_KEYWORDS


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


def is_relevant(title: str, description: str = "") -> bool:
    """Return True if title or description contains at least one keyword."""
    text = (title + " " + description).lower()
    return any(kw.lower() in text for kw in KEYWORDS)


def has_contract_signal(title: str, description: str = "") -> bool:
    """Return True if text contains explicit freelance/contract wording."""
    text = (title + " " + description).lower()
    return any(kw in text for kw in CONTRACT_KEYWORDS)


def is_contract(title: str, description: str = "", source: str = "") -> bool:
    """Return True if the listing looks like a freelance/contract assignment.

    Broker portals (Ework, Brainville, etc.) are assumed to list contracts,
    so they pass by default unless they explicitly look like permanent jobs.
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
    if source in broker_sources:
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
