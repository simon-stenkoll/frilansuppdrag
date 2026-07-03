"""Tracks seen assignment URLs to flag new vs. previously seen listings."""

import json
import os
from src.config import SOURCE_STATS_FILE
from src.models import Assignment

STATE_FILE = "state/seen.json"


def load_seen() -> set[str]:
    if not os.path.exists(STATE_FILE):
        return set()
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return set(json.load(f))


def save_seen(seen: set[str]) -> None:
    os.makedirs("state", exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(seen), f, indent=2)


def mark_new(assignments: list[Assignment]) -> list[Assignment]:
    """Set is_new=True for assignments not previously seen, then persist state."""
    seen = load_seen()
    new_urls: set[str] = set()

    for a in assignments:
        key = a.url.split("?")[0].rstrip("/")
        a.is_new = key not in seen
        new_urls.add(key)

    save_seen(seen | new_urls)
    return assignments


def check_source_health(counts: dict[str, int]) -> list[str]:
    """Return sources that yielded 0 results now but >0 last run, then persist counts.

    Catches a scraper that silently broke (site redesign, new anti-bot wall)
    the first run it happens.
    """
    previous: dict[str, int] = {}
    if os.path.exists(SOURCE_STATS_FILE):
        try:
            with open(SOURCE_STATS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                previous = data
        except (OSError, json.JSONDecodeError):
            pass

    broken = sorted(
        name for name, count in counts.items()
        if count == 0 and previous.get(name, 0) > 0
    )

    os.makedirs("state", exist_ok=True)
    with open(SOURCE_STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(counts, f, indent=2, ensure_ascii=False, sort_keys=True)

    return broken
