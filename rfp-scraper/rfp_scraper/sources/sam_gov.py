"""Federal contract opportunities in Wisconsin from the official SAM.gov API.

Requires a free public API key (sam.gov -> Account Details -> API Key) in the
SAM_API_KEY environment variable.
"""
from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Iterable

from ..dates import parse_date
from ..fetch import Fetcher
from ..models import Listing, SourceSkipped

API_URL = "https://api.sam.gov/opportunities/v2/search"
PAGE_SIZE = 1000


def parse_opportunities(data: dict, source: dict) -> list[Listing]:
    out = []
    for o in data.get("opportunitiesData") or []:
        title = o.get("title") or ""
        if not title:
            continue
        desc_bits = [o.get("type") or "", f"NAICS {o.get('naicsCode')}" if o.get("naicsCode") else ""]
        pop = o.get("placeOfPerformance") or {}
        city = (pop.get("city") or {}).get("name")
        if city:
            desc_bits.append(f"Place of performance: {city}")
        out.append(
            Listing(
                source=source["name"],
                agency=o.get("fullParentPathName") or source.get("agency", "Federal"),
                title=title,
                url=o.get("uiLink") or f"https://sam.gov/opp/{o.get('noticeId', '')}/view",
                description=". ".join(b for b in desc_bits if b),
                posted_date=parse_date(o.get("postedDate")),
                due_date=parse_date(o.get("responseDeadLine")),
                solicitation_id=o.get("solicitationNumber") or "",
            )
        )
    return out


def scrape(source: dict, fetcher: Fetcher) -> Iterable[Listing]:
    api_key = os.environ.get("SAM_API_KEY")
    if not api_key:
        raise SourceSkipped("SAM_API_KEY is not set")

    today = date.today()
    start = today - timedelta(days=int(source.get("days_back", 30)))
    seen: set[str] = set()
    results: list[Listing] = []
    for naics in source.get("naics") or [None]:
        offset = 0
        while True:
            params = {
                "api_key": api_key,
                "postedFrom": start.strftime("%m/%d/%Y"),
                "postedTo": today.strftime("%m/%d/%Y"),
                "limit": PAGE_SIZE,
                "offset": offset,
            }
            if source.get("state"):
                params["state"] = source["state"]
            if naics:
                params["ncode"] = naics
            data = fetcher.get(API_URL, params=params).json()
            for listing in parse_opportunities(data, source):
                if listing.url not in seen:
                    seen.add(listing.url)
                    results.append(listing)
            offset += PAGE_SIZE
            if offset >= int(data.get("totalRecords") or 0):
                break
    return results
