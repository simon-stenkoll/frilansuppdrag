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
    relevance_score: int = 0  # 1-10 set by LLM summarizer; 0 = not scored
