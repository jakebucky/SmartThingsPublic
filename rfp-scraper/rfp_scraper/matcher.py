"""Score listings against GRAEF's service keywords."""
from __future__ import annotations

import re

from .models import Listing, Match


def _pattern(term: str) -> re.Pattern:
    # Whole-word match; allow flexible whitespace and an optional plural "s".
    words = [re.escape(w) for w in term.lower().split()]
    body = r"\s+".join(words)
    return re.compile(rf"(?<![a-z0-9]){body}s?(?![a-z0-9])", re.IGNORECASE)


class Matcher:
    def __init__(self, config: dict):
        self.min_score = int(config.get("min_score", 2))
        self.categories: list[tuple[str, int, list[tuple[str, re.Pattern]]]] = []
        for name, cat in (config.get("categories") or {}).items():
            weight = int(cat.get("weight", 1))
            terms = [(t, _pattern(t)) for t in cat.get("terms") or []]
            self.categories.append((name, weight, terms))
        self.boosts = [(t, int(w), _pattern(t)) for t, w in (config.get("boosts") or {}).items()]
        self.exclude = [(t, _pattern(t)) for t in config.get("exclude") or []]

    def match(self, listing: Listing) -> Match:
        text = f"{listing.title}\n{listing.description}"
        for term, pat in self.exclude:
            if pat.search(text):
                return Match(score=0, excluded_by=term)

        score = 0
        categories: list[str] = []
        keywords: list[str] = []
        for name, weight, terms in self.categories:
            hit = False
            for term, pat in terms:
                if term not in keywords and pat.search(text):
                    keywords.append(term)
                    score += weight
                    hit = True
            if hit:
                categories.append(name)
        # Boosts only count once there's at least one real service match.
        if keywords:
            for term, weight, pat in self.boosts:
                if pat.search(text):
                    score += weight
        return Match(score=score, categories=categories, keywords=keywords)

    def is_relevant(self, listing: Listing) -> tuple[bool, Match]:
        m = self.match(listing)
        return m.is_relevant(self.min_score), m
