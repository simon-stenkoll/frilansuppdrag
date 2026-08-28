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


def flag_new(assignments: list[Assignment]) -> list[Assignment]:
    """Set is_new=True for assignments not previously seen. Persists nothing."""
    seen = load_seen()

    for a in assignments:
        key = a.url.split("?")[0].rstrip("/")
        a.is_new = key not in seen

    return assignments


def persist_seen(assignments: list[Assignment]) -> list[Assignment]:
    """Record classified assignments as seen, keeping every existing entry.

    Only assignments with classified=True are stored. An assignment that ran out of
    LLM budget stays "new" so the next run still has a chance to classify and mail it.
    """
    seen = load_seen()
    stored = {
        a.url.split("?")[0].rstrip("/")
        for a in assignments
        if a.classified
    }

    save_seen(seen | stored)
    return assignments
