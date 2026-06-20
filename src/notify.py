"""Posts the day's new assignments to a Discord channel via webhook.

Only assignments flagged is_new are posted. Network/config failures are logged
and swallowed so a notification problem never breaks the pipeline.
"""

import os

import httpx

from src.config import (
    DISCORD_WEBHOOK_ENV,
    DISCORD_MAX_EMBEDS,
    NOTIFY_WHEN_EMPTY,
    REQUEST_TIMEOUT,
)
from src.models import Assignment

# Discord embed colors (match the digest's score buckets)
_COLOR_HIGH = 0x43D68C  # green  (>=7)
_COLOR_MID = 0xFFD740   # yellow (4-6)
_COLOR_LOW = 0xFF6B6B   # red    (<4)


def _color(score: int) -> int:
    if score >= 7:
        return _COLOR_HIGH
    if score >= 4:
        return _COLOR_MID
    return _COLOR_LOW


def _truncate(text: str, limit: int) -> str:
    text = text or ""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _embed(a: Assignment) -> dict:
    """Build a single Discord embed for an assignment."""
    fields = [
        {"name": "Källa", "value": _truncate(a.source or "—", 256), "inline": True},
        {"name": "Plats", "value": _truncate(a.location or "—", 256), "inline": True},
    ]
    if a.relevance_score:
        fields.append({"name": "Poäng", "value": f"{a.relevance_score}/10", "inline": True})

    return {
        "title": _truncate(a.title or "(utan titel)", 256),
        "url": a.url,
        "color": _color(a.relevance_score),
        "description": _truncate(a.summary or a.description or "", 600),
        "fields": fields,
    }


def _post(webhook_url: str, payload: dict) -> None:
    resp = httpx.post(webhook_url, json=payload, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()


def post_to_discord(assignments: list[Assignment], page_url: str = "") -> None:
    """Post the new assignments to Discord. Safe to call unconditionally."""
    webhook_url = os.environ.get(DISCORD_WEBHOOK_ENV)
    if not webhook_url:
        print(f"[notify] {DISCORD_WEBHOOK_ENV} not set — skipping Discord notification")
        return

    new = [a for a in assignments if a.is_new]
    link_suffix = f"\n{page_url}" if page_url else ""

    try:
        if not new:
            if NOTIFY_WHEN_EMPTY:
                _post(webhook_url, {"content": f"📋 Inga nya konsultuppdrag idag.{link_suffix}"})
                print("[notify] Posted 'no new assignments' message to Discord")
            else:
                print("[notify] No new assignments — nothing posted")
            return

        # Sort highest-scoring first so the most relevant appear at the top.
        new.sort(key=lambda x: x.relevance_score, reverse=True)

        header = f"📋 Dagens nya konsultuppdrag ({len(new)} st){link_suffix}"
        for i in range(0, len(new), DISCORD_MAX_EMBEDS):
            batch = new[i : i + DISCORD_MAX_EMBEDS]
            payload = {"embeds": [_embed(a) for a in batch]}
            if i == 0:
                payload["content"] = header
            _post(webhook_url, payload)

        print(f"[notify] Posted {len(new)} new assignments to Discord")
    except httpx.HTTPError as e:
        print(f"[notify] Discord notification failed: {type(e).__name__}: {e}")
