"""Tracks seen assignment URLs to flag new vs. previously seen listings."""

import json
import os
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
