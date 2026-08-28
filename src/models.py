"""Shared data models."""

from dataclasses import dataclass, field
from datetime import date


@dataclass
class Assignment:
    title: str
    company: str
    location: str
    description: str
    url: str
    source: str
    date_found: str = field(default_factory=lambda: date.today().isoformat())
    is_new: bool = True
    summary: str = ""
    relevance_score: int = 0  # 1-10 set by the LLM classifier; 0 = not scored
    # Set by src/classifier.py
    employment_type: str = ""       # "contract" | "permanent" | "unclear"
    role_match: str = ""            # "core" | "adjacent" | "none"
    location_ok: bool | None = None  # True/False, or None when the ad does not say
    status: str = ""                # "open" | "filled" | "paused" | "unknown"
    classified: bool = False        # True only after a validated classification
