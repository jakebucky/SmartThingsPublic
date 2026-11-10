from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date


@dataclass
class Listing:
    """One solicitation as found on a source, before keyword matching."""

    source: str
    agency: str
    title: str
    url: str
    description: str = ""
    posted_date: date | None = None
    due_date: date | None = None
    solicitation_id: str = ""
    agency_type: str = ""

    @property
    def uid(self) -> str:
        key = f"{self.source}|{self.url}|{self.title.strip().lower()}"
        return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


@dataclass
class Match:
    score: int
    categories: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    excluded_by: str | None = None

    def is_relevant(self, min_score: int) -> bool:
        return self.excluded_by is None and self.score >= min_score


class SourceSkipped(Exception):
    """A source can't run for a configuration reason (e.g. missing API key)."""
