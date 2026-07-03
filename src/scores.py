"""Caches LLM relevance scores per assignment URL between runs."""

import json
import os
from datetime import date, timedelta

from src.config import SCORES_STATE_FILE, SCORES_MAX_AGE_DAYS


def url_key(url: str) -> str:
    """Normalize a URL the same way as state.mark_new does."""
    return url.split("?")[0].rstrip("/")


def load_scores() -> dict[str, dict]:
    if not os.path.exists(SCORES_STATE_FILE):
        return {}
    try:
        with open(SCORES_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_scores(scores: dict[str, dict]) -> None:
    cutoff = (date.today() - timedelta(days=SCORES_MAX_AGE_DAYS)).isoformat()
    pruned = {
        key: entry
        for key, entry in scores.items()
        if entry.get("scored_at", "") >= cutoff
    }
    os.makedirs("state", exist_ok=True)
    with open(SCORES_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(pruned, f, indent=2, ensure_ascii=False, sort_keys=True)
