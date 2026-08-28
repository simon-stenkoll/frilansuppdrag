"""Legacy generic HTML extraction, kept ONLY for src/discovery.py.

These helpers come from the removed broker_portals module. Discovery uses them to
score whether a broker page looks like it lists assignments. They are not part of the
nightly pipeline any more and nothing else should import them: etapp 5 replaces
discovery and this module goes away with it.

The only change from the original is that the keyword contract filter is gone, since
the LLM classifier is the pipeline's decision gate now.
"""

from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from src.models import Assignment
from src.scrapers.utils import is_relevant, is_in_stockholm, clean_text


def _base_url(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _try_assignment(
    title: str, description: str, location: str, url: str,
    source: str, seen_urls: set[str],
) -> Assignment | None:
    """Create an Assignment if it passes the cheap keyword and location filters."""
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


def _extract_from_soup(
    soup: BeautifulSoup, base: str, name: str, seen_urls: set[str],
) -> list[Assignment]:
    """Extract assignments from already-parsed portal HTML (HTTP or rendered)."""
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
        if not is_relevant(link_text, context):
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
