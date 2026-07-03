"""LLM-based summarization and relevance scoring using GitHub Models API."""

import os
import json
import time
from datetime import date

from openai import OpenAI

from src.config import (
    GITHUB_MODELS_MODEL,
    GITHUB_MODELS_ENDPOINT,
    LLM_MAX_RETRIES,
    LLM_RETRY_BACKOFF,
    LLM_REQUEST_DELAY,
)
from src.cv_profile import get_consultant_cv_profile
from src.models import Assignment
from src.scores import load_scores, save_scores, url_key


def _client() -> OpenAI | None:
    token = os.environ.get("GITHUB_MODELS_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        return None
    return OpenAI(base_url=GITHUB_MODELS_ENDPOINT, api_key=token)


def _build_prompt(a: Assignment, consultant_cv_profile: str) -> str:
    return (
        "You are scoring how well a contract/freelance assignment matches a specific "
        "consultant profile. The score must reflect PROFILE MATCH, not how attractive "
        "the assignment is in general.\n\n"
        "Consultant profile:\n"
        "- Senior freelance consultant in Stockholm, Sweden (5-10 years experience).\n"
        "- Focus areas: Data Engineering, BI/Analytics, Data Platform/Architecture, "
        "Analytics Engineering.\n"
        "- Open to assignments in Stockholm or remote within Sweden.\n\n"
        f"Consultant CV evidence:\n{consultant_cv_profile}\n\n"
        f"Assignment:\nTitle: {a.title}\nCompany: {a.company}\nLocation: {a.location}\n"
        f"Description: {a.description or '(no description)'}\n\n"
        'Respond ONLY with valid JSON: {"score": <1-10>, "summary": "<1-2 meningars '
        'sammanfattning på svenska>"}\n'
        "Use the FULL 1-10 scale and commit to a judgment — never fall back to 5 when unsure.\n"
        "Score criteria:\n"
        "- 9-10: Clear freelance/contract assignment squarely in the focus areas, strong "
        "overlap with CV technologies, senior-level responsibilities\n"
        "- 7-8: Contract assignment in data/analytics with moderate CV overlap\n"
        "- 4-6: Adjacent role or tech stack, or too vague a description to judge the fit\n"
        "- 1-3: Junior-level role, role outside data/BI/platform, or permanent employment\n"
        "Heavily penalize listings that appear to be permanent employment or junior positions."
    )


def _score_one(client: OpenAI, prompt: str) -> tuple[int, str]:
    """Score a single assignment; raises the last error after exhausting retries."""
    last_error: Exception = RuntimeError("no attempts made")
    for attempt in range(LLM_MAX_RETRIES):
        if attempt:
            time.sleep(LLM_RETRY_BACKOFF * (2 ** (attempt - 1)))
        try:
            resp = client.chat.completions.create(
                model=GITHUB_MODELS_MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=150,
                temperature=0.2,
                response_format={"type": "json_object"},
            )
            data = json.loads(resp.choices[0].message.content)
            score = int(data["score"])
            return max(1, min(10, score)), str(data.get("summary", ""))
        except Exception as e:
            last_error = e
    raise last_error


def summarize(assignments: list[Assignment]) -> list[Assignment]:
    """
    For each assignment, ask the LLM to:
    - Rate profile match 1-10 against the consultant CV profile
    - Write a 1-2 sentence summary

    Scores are cached in state/scores.json so only unseen assignments cost LLM calls.
    Assignments that cannot be scored keep relevance_score=0 ("not scored") — never a
    fake middle-of-the-scale default.
    """
    if not assignments:
        return assignments

    client = _client()
    if client is None:
        print("[summarize] GITHUB_MODELS_TOKEN not set — leaving all assignments unscored")
        assignments.sort(key=lambda x: (x.relevance_score, x.is_new), reverse=True)
        return assignments

    consultant_cv_profile = get_consultant_cv_profile()
    cache = load_scores()
    today = date.today().isoformat()

    cached_count = scored_count = failed_count = 0
    for a in assignments:
        key = url_key(a.url)
        hit = cache.get(key)
        if hit and isinstance(hit.get("score"), int):
            a.relevance_score = hit["score"]
            a.summary = str(hit.get("summary", ""))
            cached_count += 1
            continue

        try:
            score, summary = _score_one(client, _build_prompt(a, consultant_cv_profile))
            a.relevance_score = score
            a.summary = summary
            cache[key] = {"score": score, "summary": summary, "scored_at": today}
            scored_count += 1
        except Exception as e:
            a.relevance_score = 0
            a.summary = ""
            failed_count += 1
            print(f"[summarize] FAILED '{a.title[:60]}': {type(e).__name__}: {e}")
        time.sleep(LLM_REQUEST_DELAY)

    save_scores(cache)
    print(f"[summarize] {scored_count} scored, {cached_count} from cache, {failed_count} failed")

    # Sort by relevance score descending; unscored (0) last, new first within same score
    assignments.sort(key=lambda x: (x.relevance_score, x.is_new), reverse=True)
    return assignments
