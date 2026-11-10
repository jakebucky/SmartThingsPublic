from __future__ import annotations

from typing import Callable, Iterable

from ..fetch import Fetcher
from ..models import Listing, SourceSkipped  # noqa: F401 (re-export)
from . import bonfire, html_page, sam_gov

SourceFn = Callable[[dict, Fetcher], Iterable[Listing]]

REGISTRY: dict[str, SourceFn] = {
    "html": html_page.scrape,
    "bonfire": bonfire.scrape,
    "sam_gov": sam_gov.scrape,
}


def get_scraper(source_type: str) -> SourceFn:
    try:
        return REGISTRY[source_type]
    except KeyError:
        raise ValueError(f"Unknown source type '{source_type}'. Known: {', '.join(REGISTRY)}")
