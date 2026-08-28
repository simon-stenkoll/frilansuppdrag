"""Tracks seen assignment URLs to flag new vs. previously seen listings.

state/seen.json maps a normalized URL to the date it was last seen:

    {"https://example.com/uppdrag/1": "2026-08-28", ...}

The old list-only format is still read and is converted on the first save, so no
manual migration is needed. Entries that have not been seen for SEEN_MAX_AGE_DAYS
are dropped when the file is written.
"""

import json
import os
from datetime import date, timedelta

from src.config import SEEN_MAX_AGE_DAYS
from src.models import Assignment

STATE_FILE = "state/seen.json"


def url_key(url: str) -> str:
    """Normalize a URL to the key used in the seen state."""
    return (url or "").split("?")[0].rstrip("/")


def _valid_date(value) -> str:
    """Return value as an ISO date string, falling back to today when unusable."""
    if isinstance(value, str):
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError:
            pass
    return date.today().isoformat()


def load_seen() -> dict[str, str]:
    """Load the seen state as {url_key: last_seen_date}.

    Accepts both the current object format and the legacy list format, where every
    entry is treated as seen today.
    """
    if not os.path.exists(STATE_FILE):
        return {}
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    today = date.today().isoformat()
    if isinstance(data, list):
        return {key: today for key in data if isinstance(key, str)}
    if isinstance(data, dict):
        return {
            key: _valid_date(value)
            for key, value in data.items()
            if isinstance(key, str)
        }
    return {}


def save_seen(seen: dict[str, str]) -> None:
    """Write the seen state, dropping entries older than SEEN_MAX_AGE_DAYS."""
    cutoff = (date.today() - timedelta(days=SEEN_MAX_AGE_DAYS)).isoformat()
    kept = {key: value for key, value in seen.items() if value >= cutoff}

    os.makedirs("state", exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({key: kept[key] for key in sorted(kept)}, f, indent=2)


def flag_new(assignments: list[Assignment]) -> list[Assignment]:
    """Set is_new=True for assignments not previously seen. Persists nothing."""
    seen = load_seen()

    for a in assignments:
        a.is_new = url_key(a.url) not in seen

    return assignments


def persist_seen(assignments: list[Assignment]) -> list[Assignment]:
    """Record classified assignments as seen and refresh the dates of known ones.

    Only assignments with classified=True are added. An assignment that ran out of
    LLM budget stays "new" so the next run still has a chance to classify and mail it.
    Assignments already in the state get today's date whether or not they were
    classified, so a listing that keeps showing up is not pruned as stale.
    """
    seen = load_seen()
    today = date.today().isoformat()

    for a in assignments:
        key = url_key(a.url)
        if not key:
            continue
        if a.classified or key in seen:
            seen[key] = today

    save_seen(seen)
    return assignments
