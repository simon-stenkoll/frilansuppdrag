"""LLM classification gate: structured verdicts on every scraped assignment.

Replaces the old keyword-only contract filter plus free-text summarizer with a single
LLM call per assignment that returns employment type, role match, location, status,
a 1-10 profile score and a Swedish summary. Assignments are never dropped here: an
assignment the LLM could not classify simply keeps classified=False.
"""

import json
import re
import time
from dataclasses import dataclass
from typing import Any

from openai import (
    AuthenticationError,
    OpenAI,
    PermissionDeniedError,
    RateLimitError,
)

from src.classify_cache import (
    cache_hit,
    content_hash,
    load_classifications,
    make_entry,
    save_classifications,
    url_key,
)
from src.config import (
    LLM_MODEL,
    LLM_MAX_RETRIES,
    LLM_RETRY_BACKOFF,
    LLM_REQUEST_DELAY,
    LLM_RUN_BUDGET,
)
from src.cv_profile import get_consultant_cv_profile
from src.llm import api_key_env_name, make_llm_client
from src.models import Assignment

EMPLOYMENT_TYPES = {"contract", "permanent", "unclear"}
ROLE_MATCHES = {"core", "adjacent", "none"}
STATUSES = {"open", "filled", "paused", "unknown"}

# Attempts per assignment when the model answers with invalid JSON or invalid fields.
VALIDATION_ATTEMPTS = 2
# Consecutive rate-limit failures before the whole LLM pass gives up for this run.
RATE_LIMIT_ABORT_AFTER = 3

# Cheap status signals, checked without the LLM on every run (cache hits included).
_FILLED_PATTERN = re.compile(r"\b(tillsatt|closed|filled)\b", re.IGNORECASE)
_PAUSED_PATTERN = re.compile(r"\b(pausad|paused|on hold)\b", re.IGNORECASE)


class LlmBudget:
    """Shared counter for LLM calls in one pipeline run.

    Kept deliberately generic so a future portal-extraction module can take the same
    instance and compete for the same budget.
    """

    def __init__(self, limit: int = LLM_RUN_BUDGET):
        self.limit = limit
        self.used = 0

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)

    def spend(self, calls: int = 1) -> bool:
        """Reserve `calls` from the budget. Returns False when nothing is left."""
        if calls <= 0 or self.remaining < calls:
            return False
        self.used += calls
        return True


@dataclass
class ClassifyStats:
    """Outcome of one classify() pass, filled in for the caller.

    Passed in by the caller (main.py) instead of changing the return type, so the
    existing `classified = classify(...)` call site keeps working unchanged.
    `auth_error` is set only when a 401/403 aborted the run, `last_error` holds the
    most recent per-assignment error text whatever the cause.
    """

    classified: int = 0
    cached: int = 0
    failed: int = 0
    deferred: int = 0
    auth_error: str = ""
    last_error: str = ""

    @property
    def needed_llm(self) -> int:
        """Assignments that were not served from cache and needed an LLM call."""
        return self.classified + self.failed + self.deferred

    @property
    def is_degraded(self) -> bool:
        """True when LLM classification was needed but produced nothing at all.

        Cause does not matter: auth error, everything deferred, everything failed or a
        mix of them. Scattered failures without a single successful answer are an
        outage, not noise (a BOM-corrupt API key once made all 33 calls raise client
        side, which passed as a green run).
        """
        return self.needed_llm > 0 and self.classified == 0


def build_prompt(a: Assignment, consultant_cv_profile: str) -> str:
    """Build the classification prompt for one assignment."""
    return (
        "You classify Swedish job and assignment listings for a freelance data consultant. "
        "Answer ONLY with valid JSON, no markdown fences, no commentary.\n\n"
        "Consultant profile:\n"
        "- Freelance consultant based in Stockholm, Sweden, invoicing through his own company.\n"
        "- Focus areas: Data Engineering, BI/Analytics, Data Platform/Architecture, "
        "Analytics Engineering.\n"
        "- Takes assignments in the Stockholm area or remote within Sweden.\n\n"
        f"Consultant CV evidence:\n{consultant_cv_profile}\n\n"
        "Listing:\n"
        f"Title: {a.title}\n"
        f"Company: {a.company}\n"
        f"Location: {a.location}\n"
        f"Source: {a.source}\n"
        f"Description: {a.description or '(no description)'}\n\n"
        "Return exactly this JSON shape:\n"
        '{"employment_type": "contract"|"permanent"|"unclear", '
        '"role_match": "core"|"adjacent"|"none", '
        '"location_ok": true|false|null, '
        '"status": "open"|"filled"|"paused"|"unknown", '
        '"score": 1-10, '
        '"summary": "<1-2 sentences in Swedish>"}\n\n'
        "Field definitions:\n"
        "employment_type: use \"contract\" ONLY for a freelance, subcontractor or interim "
        "ASSIGNMENT, meaning a time limited engagement where the consultant invoices for his "
        "work or is placed through a broker. Use \"permanent\" for employment, INCLUDING "
        "employment as a consultant at a consultancy firm (for example Castra, Liminity or "
        "CoreChange hiring employed consultants). The words \"konsult\" or \"uppdrag\" appearing "
        "in navigation text or boilerplate do not make a listing a contract. Use \"unclear\" "
        "when the listing genuinely does not say.\n"
        "role_match: \"core\" for Data Engineer, Analytics Engineer, BI developer, "
        "Data/Analytics Platform Engineer. \"adjacent\" for Data Scientist, Data Analyst, "
        "backend roles with a heavy data component, DBA, Data Architect. \"none\" for anything "
        "else.\n"
        "location_ok: true for the Stockholm area, Stockholm hybrid, or remote within Sweden. "
        "false for a clearly different city or country. null when the listing does not say.\n"
        "status: \"filled\" when the listing says it is tillsatt or closed, \"paused\" when it is "
        "pausad or on hold, otherwise \"open\", or \"unknown\" when it cannot be told.\n"
        "score: an integer 1-10 measuring ONLY the technology and domain overlap between the "
        "listing and the CV evidence above. Seniority level (junior/senior/lead) MUST NOT "
        "affect the score in any direction. Employment type and location MUST NOT affect the "
        "score either, they are reported in their own fields. Use the full 1-10 scale and "
        "commit to a judgment, never fall back to 5 when unsure.\n"
        "summary: 1-2 sentences in Swedish describing what the listing is. Do not use em "
        "dashes, use commas or parentheses instead."
    )


def validate_result(raw: str) -> dict[str, Any] | None:
    """Parse and field-validate a model answer. Returns None when anything is off."""
    text = raw.strip()
    # Some models wrap the JSON in markdown fences despite response_format.
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    try:
        data = json.loads(text)
    except Exception:
        return None
    return validate_fields(data)


def validate_fields(data: Any) -> dict[str, Any] | None:
    """Field-validate an already parsed record. Returns None when anything is off."""
    if not isinstance(data, dict):
        return None

    employment_type = data.get("employment_type")
    role_match = data.get("role_match")
    status = data.get("status")
    location_ok = data.get("location_ok")

    if employment_type not in EMPLOYMENT_TYPES:
        return None
    if role_match not in ROLE_MATCHES:
        return None
    if status not in STATUSES:
        return None
    if location_ok is not None and not isinstance(location_ok, bool):
        return None

    try:
        score = int(data["score"])
    except Exception:
        return None

    summary = data.get("summary", "")
    if not isinstance(summary, str):
        return None

    return {
        "employment_type": employment_type,
        "role_match": role_match,
        "location_ok": location_ok,
        "status": status,
        "score": max(1, min(10, score)),
        "summary": summary.strip(),
    }


def status_override(a: Assignment) -> str:
    """Cheap keyword status check against the fresh title and description, no LLM."""
    text = f"{a.title or ''} {a.description or ''}"
    if _FILLED_PATTERN.search(text):
        return "filled"
    if _PAUSED_PATTERN.search(text):
        return "paused"
    return ""


def _apply(a: Assignment, result: dict[str, Any]) -> None:
    a.employment_type = result["employment_type"]
    a.role_match = result["role_match"]
    a.location_ok = result["location_ok"]
    a.status = result["status"]
    a.relevance_score = result["score"]
    a.summary = result["summary"]
    a.classified = True


def _call_llm(client: OpenAI, prompt: str) -> str:
    """One completion with transport retries. Raises the last error when exhausted."""
    last_error: Exception = RuntimeError("no attempts made")
    for attempt in range(LLM_MAX_RETRIES):
        if attempt:
            time.sleep(LLM_RETRY_BACKOFF * (2 ** (attempt - 1)))
        try:
            resp = client.chat.completions.create(
                model=LLM_MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=250,
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            return resp.choices[0].message.content or ""
        except (AuthenticationError, PermissionDeniedError):
            raise  # 401/403 are permanent, retrying only wastes time
        except Exception as e:
            last_error = e
    raise last_error


def _classify_one(client: OpenAI, prompt: str) -> dict[str, Any] | None:
    """Classify one assignment. Returns None when the answer stays invalid."""
    for attempt in range(VALIDATION_ATTEMPTS):
        if attempt:
            time.sleep(LLM_REQUEST_DELAY)
        result = validate_result(_call_llm(client, prompt))
        if result is not None:
            return result
    return None


def _priority_order(assignments: list[Assignment]) -> list[Assignment]:
    """New assignments first, then the remaining unclassified ones."""
    return [a for a in assignments if a.is_new] + [a for a in assignments if not a.is_new]


def classify(
    assignments: list[Assignment],
    budget: LlmBudget | None = None,
    stats: ClassifyStats | None = None,
) -> list[Assignment]:
    """
    Classify every assignment with one LLM call each, cached in state/classifications.json.

    Assignments are never dropped: anything that cannot be classified (missing token,
    exhausted budget, invalid answers, rate limits) keeps classified=False so the next
    run picks it up again. The cheap keyword status override runs on every assignment,
    cache hits included, so a listing that has since been filled is caught without an
    LLM call.

    When `stats` is given it is filled with the run counters so the caller can tell a
    normal run from a total LLM outage.
    """
    if not assignments:
        return assignments

    if budget is None:
        budget = LlmBudget()

    cache = load_classifications()
    client = make_llm_client()
    if client is None:
        print(f"[classify] {api_key_env_name()} saknas, kör bara cache och statuskoll")

    consultant_cv_profile = get_consultant_cv_profile() if client is not None else ""

    cached_count = classified_count = failed_count = deferred_count = 0
    rate_limit_streak = 0
    calls_made = 0
    llm_disabled = client is None
    auth_error = ""
    last_error = ""

    for a in _priority_order(assignments):
        key = url_key(a.url)
        hash_value = content_hash(a.title, a.description)
        entry = cache.get(key)

        if cache_hit(entry, hash_value):
            result = validate_fields(entry)
            if result is not None:
                _apply(a, result)
                cached_count += 1
                continue
            # A corrupt record is treated as a miss rather than trusted.

        if llm_disabled:
            deferred_count += 1
            continue

        if not budget.spend():
            llm_disabled = True
            deferred_count += 1
            print(f"[classify] LLM-budgeten ({budget.limit} anrop) är slut, "
                  "resterande uppdrag skjuts upp till nästa körning")
            continue

        # Space out calls whatever the outcome, a failed call still hit the rate limit.
        if calls_made:
            time.sleep(LLM_REQUEST_DELAY)
        calls_made += 1

        try:
            result = _classify_one(client, build_prompt(a, consultant_cv_profile))
        except (AuthenticationError, PermissionDeniedError) as e:
            llm_disabled = True
            deferred_count += 1
            auth_error = f"{type(e).__name__}: {e}"
            print(f"[classify] ABORTED, auth error, hoppar över resterande uppdrag: "
                  f"{auth_error}")
            continue
        except RateLimitError as e:
            rate_limit_streak += 1
            failed_count += 1
            last_error = f"{type(e).__name__}: {e}"
            print(f"[classify] RATELIMIT '{a.title[:60]}': {last_error}")
            if rate_limit_streak >= RATE_LIMIT_ABORT_AFTER:
                llm_disabled = True
                print(f"[classify] ABORTED, {rate_limit_streak} ratelimit-fel i rad, "
                      "avbryter LLM-delen för den här körningen")
            continue
        except Exception as e:
            rate_limit_streak = 0
            failed_count += 1
            last_error = f"{type(e).__name__}: {e}"
            print(f"[classify] FAILED '{a.title[:60]}': {last_error}")
            continue

        rate_limit_streak = 0
        if result is None:
            failed_count += 1
            last_error = "InvalidResponse: modellen svarade inte med giltig JSON"
            print(f"[classify] INVALID '{a.title[:60]}': modellen svarade inte med giltig JSON")
            continue

        _apply(a, result)
        cache[key] = make_entry(result, hash_value)
        classified_count += 1

    # Cheap status override, applied every run so stale cache entries cannot hide a
    # listing that has since been filled or paused.
    overridden = 0
    for a in assignments:
        override = status_override(a)
        if override and a.status != override:
            a.status = override
            overridden += 1

    save_classifications(cache)
    print(f"[classify] {classified_count} klassificerade, {cached_count} från cache, "
          f"{failed_count} misslyckade, {deferred_count} uppskjutna "
          f"(budget {budget.used}/{budget.limit})")
    if overridden:
        print(f"[classify] {overridden} uppdrag statusöverstyrda av nyckelord")

    if stats is not None:
        stats.classified = classified_count
        stats.cached = cached_count
        stats.failed = failed_count
        stats.deferred = deferred_count
        stats.auth_error = auth_error
        stats.last_error = last_error

    # Sort by score descending, unclassified (0) last, new first within the same score
    assignments.sort(key=lambda x: (x.relevance_score, x.is_new), reverse=True)
    return assignments
