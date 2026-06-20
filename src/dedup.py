"""Deduplicates assignments across scrapers using URL + fuzzy title matching."""

from src.models import Assignment


def deduplicate(assignments: list[Assignment]) -> list[Assignment]:
    seen_urls: set[str] = set()
    seen_titles: list[str] = []
    out: list[Assignment] = []

    for a in assignments:
        normalized_url = a.url.split("?")[0].rstrip("/")
        if normalized_url in seen_urls:
            continue
        seen_urls.add(normalized_url)

        title_key = _normalize_title(a.title)
        if any(_similar(title_key, t) for t in seen_titles):
            continue
        seen_titles.append(title_key)

        out.append(a)

    return out


def _normalize_title(title: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    import re
    return re.sub(r"\W+", " ", title.lower()).strip()


def _similar(a: str, b: str, threshold: float = 0.8) -> bool:
    """Simple overlap-based similarity check (no external deps)."""
    words_a = set(a.split())
    words_b = set(b.split())
    if not words_a or not words_b:
        return False
    overlap = len(words_a & words_b)
    return overlap / max(len(words_a), len(words_b)) >= threshold
