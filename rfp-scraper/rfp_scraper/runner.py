"""Run every enabled source, keep the relevant listings, store them."""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field

from .fetch import Fetcher
from .matcher import Matcher
from .models import SourceSkipped
from .sources import get_scraper
from . import db

log = logging.getLogger("rfp_scraper")


@dataclass
class RunSummary:
    sources: int = 0
    listings: int = 0
    matched: int = 0
    new: int = 0
    errors: list[str] = field(default_factory=list)


def run(
    conn: sqlite3.Connection,
    sources: list[dict],
    keywords: dict,
    *,
    only: list[str] | None = None,
    fetcher: Fetcher | None = None,
) -> RunSummary:
    matcher = Matcher(keywords)
    fetcher = fetcher or Fetcher()
    summary = RunSummary()

    for source in sources:
        if not source.get("enabled", True):
            continue
        if only and not any(o.lower() in source["name"].lower() for o in only):
            continue
        summary.sources += 1
        run_id = db.start_run(conn, source["name"])
        try:
            listings = list(get_scraper(source["type"])(source, fetcher))
        except SourceSkipped as exc:
            log.info("%s: skipped (%s)", source["name"], exc)
            db.finish_run(conn, run_id, status="skipped", message=str(exc))
            continue
        except Exception as exc:  # one broken site must not stop the rest
            msg = f"{type(exc).__name__}: {exc}"
            log.warning("%s: %s", source["name"], msg)
            summary.errors.append(f"{source['name']}: {msg}")
            db.finish_run(conn, run_id, status="error", message=msg)
            continue

        matched = new = 0
        for listing in listings:
            relevant, match = matcher.is_relevant(listing)
            if not relevant:
                continue
            matched += 1
            if db.upsert_rfp(conn, listing, match):
                new += 1
        conn.commit()
        summary.listings += len(listings)
        summary.matched += matched
        summary.new += new
        log.info("%s: %d listings, %d relevant, %d new", source["name"], len(listings), matched, new)
        db.finish_run(conn, run_id, status="ok", listings=len(listings), matched=matched, new_matches=new)
    return summary
