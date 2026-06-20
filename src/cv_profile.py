"""Build a compact consultant profile from local CV YAML files."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

CV_FILENAMES = (
    "CV - Simon Stenlund (Eng).yaml",
    "CV - Simon Stenlund (Swe).yaml",
)

FALLBACK_PROFILE = (
    "Freelance Data Engineer in Stockholm with 6+ years experience in data warehousing, "
    "ETL, BI reporting, and team leadership. Core stack: Microsoft Fabric, Power BI, "
    "Azure Data Factory, Azure Synapse, Snowflake, dbt, DAX, SQL, PySpark."
)


def _normalize_text(value: object) -> str:
    if not value:
        return ""
    return " ".join(str(value).split())


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _dedupe_keep_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        key = value.casefold()
        if not value or key in seen:
            continue
        seen.add(key)
        output.append(value)
    return output


def _load_cv(path: Path) -> dict:
    if not path.exists():
        return {}

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}

    return data if isinstance(data, dict) else {}


@lru_cache(maxsize=1)
def get_consultant_cv_profile() -> str:
    root_dir = Path(__file__).resolve().parents[1]
    cv_docs = [_load_cv(root_dir / filename) for filename in CV_FILENAMES]
    cv_docs = [doc for doc in cv_docs if doc]

    if not cv_docs:
        return FALLBACK_PROFILE

    about_sections: list[str] = []
    technologies: list[str] = []
    assignment_lines: list[str] = []
    bullet_highlights: list[str] = []
    seen_assignments: set[str] = set()

    for doc in cv_docs:
        about_text = _normalize_text(doc.get("about"))
        if about_text:
            about_sections.append(about_text)

        for tech_group in _as_list(doc.get("technology")):
            if not isinstance(tech_group, dict):
                continue
            for item in _as_list(tech_group.get("items")):
                item_text = _normalize_text(item)
                if item_text:
                    technologies.append(item_text)

        for assignment in _as_list(doc.get("assignments")):
            if not isinstance(assignment, dict):
                continue

            role = _normalize_text(assignment.get("role"))
            company = _normalize_text(assignment.get("company"))
            period = _normalize_text(assignment.get("period"))

            assignment_key = f"{role}::{company}".casefold()
            if role and company and assignment_key not in seen_assignments:
                seen_assignments.add(assignment_key)
                if period:
                    assignment_lines.append(f"{role} @ {company} ({period})")
                else:
                    assignment_lines.append(f"{role} @ {company}")

            for bullet in _as_list(assignment.get("bullets")):
                bullet_text = _normalize_text(bullet)
                if bullet_text:
                    bullet_highlights.append(bullet_text)

    about_sections = _dedupe_keep_order(about_sections)
    technologies = _dedupe_keep_order(technologies)
    assignment_lines = _dedupe_keep_order(assignment_lines)
    bullet_highlights = _dedupe_keep_order(bullet_highlights)

    lines = ["Consultant CV evidence compiled from English and Swedish CVs."]

    if about_sections:
        lines.append("Profile: " + " ".join(about_sections))
    if technologies:
        lines.append("Core technologies: " + ", ".join(technologies))
    if assignment_lines:
        lines.append("Relevant assignments: " + "; ".join(assignment_lines[:8]))
    if bullet_highlights:
        lines.append("Selected achievements: " + " | ".join(bullet_highlights[:8]))

    return "\n".join(lines)
