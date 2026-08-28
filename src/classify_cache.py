"""Caches LLM classifications per assignment URL between runs."""

import hashlib
import json
import os
from datetime import date, timedelta

from src.config import (
    CLASSIFIER_PROMPT_VERSION,
    CLASSIFY_MAX_AGE_DAYS,
    CLASSIFY_STATE_FILE,
)

# Number of description characters that feed the content hash. Enough to notice a
# rewritten ad, short enough that boilerplate footers do not churn the cache.
_HASH_DESCRIPTION_CHARS = 1500


def url_key(url: str) -> str:
    """Normalize a URL the same way as state.flag_new does."""
    return url.split("?")[0].rstrip("/")


def content_hash(title: str, description: str) -> str:
    """Fingerprint the ad text so edited listings get re-classified."""
    payload = f"{title or ''}\n{(description or '')[:_HASH_DESCRIPTION_CHARS]}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def load_classifications() -> dict[str, dict]:
    if not os.path.exists(CLASSIFY_STATE_FILE):
        return {}
    try:
        with open(CLASSIFY_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_classifications(cache: dict[str, dict]) -> None:
    cutoff = (date.today() - timedelta(days=CLASSIFY_MAX_AGE_DAYS)).isoformat()
    pruned = {
        key: entry
        for key, entry in cache.items()
        if str(entry.get("classified_at", "")) >= cutoff
    }
    os.makedirs("state", exist_ok=True)
    with open(CLASSIFY_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(pruned, f, indent=2, ensure_ascii=False, sort_keys=True)


def cache_hit(entry: dict | None, expected_hash: str) -> bool:
    """A cached record is usable only for identical text and the same prompt version."""
    if not isinstance(entry, dict):
        return False
    if entry.get("content_hash") != expected_hash:
        return False
    return entry.get("prompt_version") == CLASSIFIER_PROMPT_VERSION


def make_entry(result: dict, hash_value: str) -> dict:
    """Build a cache record from a validated classification result."""
    return {
        "content_hash": hash_value,
        "employment_type": result["employment_type"],
        "role_match": result["role_match"],
        "location_ok": result["location_ok"],
        "status": result["status"],
        "score": result["score"],
        "summary": result["summary"],
        "prompt_version": CLASSIFIER_PROMPT_VERSION,
        "classified_at": date.today().isoformat(),
    }
