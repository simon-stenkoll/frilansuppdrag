"""LLM-based summarization and relevance scoring using GitHub Models API."""

import os
import json
from openai import OpenAI
from src.config import GITHUB_MODELS_MODEL, GITHUB_MODELS_ENDPOINT
from src.cv_profile import get_consultant_cv_profile
from src.models import Assignment


def _client() -> OpenAI:
    token = os.environ.get("GITHUB_MODELS_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise EnvironmentError("GITHUB_MODELS_TOKEN environment variable is not set.")
    return OpenAI(base_url=GITHUB_MODELS_ENDPOINT, api_key=token)


def summarize(assignments: list[Assignment]) -> list[Assignment]:
    """
    For each assignment, ask the LLM to:
    - Rate relevance 1-10 for a Data Engineer / BI / Analytics consultant in Stockholm
    - Write a 1-2 sentence summary

    Falls back gracefully if the API is unavailable.
    """
    if not assignments:
        return assignments

    client = _client()
    consultant_cv_profile = get_consultant_cv_profile()

    for a in assignments:
        prompt = (
            f"You are evaluating contract/freelance assignments for a freelance Data Engineer in Stockholm.\n"
            f"Use the consultant CV evidence below (compiled from both English and Swedish CV files) to assess fit. "
            f"Give higher scores when the assignment matches multiple technologies, responsibilities, and seniority "
            f"signals from the CV evidence.\n\n"
            f"Consultant CV evidence:\n{consultant_cv_profile}\n\n"
            f"Assignment:\nTitle: {a.title}\nCompany: {a.company}\nLocation: {a.location}\n"
            f"Description: {a.description or '(no description)'}\n\n"
            f"Respond ONLY with valid JSON: {{\"score\": <1-10>, \"summary\": \"<1-2 sentence summary>\"}}\n"
            f"Score criteria:\n"
            f"- 9-10: Clear freelance/contract assignment with strong overlap to CV technologies and similar delivery responsibilities\n"
            f"- 7-8: Contract assignment in data/analytics with moderate CV overlap\n"
            f"- 4-6: Potentially relevant but weak CV overlap or unclear if it is freelance/contract\n"
            f"- 1-3: Permanent employment position, or completely unrelated to data engineering/BI\n"
            f"Heavily penalize listings that appear to be permanent employment rather than freelance/contract assignments."
        )
        try:
            resp = client.chat.completions.create(
                model=GITHUB_MODELS_MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=150,
                temperature=0.2,
            )
            raw = resp.choices[0].message.content.strip()
            # Strip markdown code fences if present
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            data = json.loads(raw)
            score = int(data.get("score", 5))
            a.relevance_score = max(1, min(10, score))
            a.summary = str(data.get("summary", ""))
        except Exception:
            a.relevance_score = 5
            a.summary = ""

    # Sort by relevance score descending; within the same score, new assignments first
    assignments.sort(key=lambda x: (x.relevance_score, x.is_new), reverse=True)
    return assignments
