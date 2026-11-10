"""Agencies that publish on Bonfire (<org>.bonfirehub.com).

The public portal page is rendered with JavaScript, but it loads its open
opportunities from a JSON endpoint, which we read directly.
"""
from __future__ import annotations

import time
from typing import Iterable

from ..dates import parse_date
from ..fetch import Fetcher
from ..models import Listing


def _projects(payload) -> list[dict]:
    if isinstance(payload, dict):
        projects = payload.get("projects", payload)
        if isinstance(projects, dict):
            return [p for p in projects.values() if isinstance(p, dict)]
        if isinstance(projects, list):
            return [p for p in projects if isinstance(p, dict)]
    if isinstance(payload, list):
        return [p for p in payload if isinstance(p, dict)]
    return []


def _first(d: dict, *keys: str) -> str:
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return str(v)
    return ""


def parse_projects(data: dict, source: dict) -> list[Listing]:
    org = source["org"]
    base = f"https://{org}.bonfirehub.com"
    out = []
    for p in _projects(data.get("payload", data)):
        pid = _first(p, "ProjectID", "projectID", "id")
        title = _first(p, "ProjectName", "projectName", "name", "title")
        if not title:
            continue
        out.append(
            Listing(
                source=source["name"],
                agency=source.get("agency", source["name"]),
                title=title,
                url=f"{base}/opportunities/{pid}" if pid else f"{base}/portal/?tab=openOpportunities",
                description=_first(p, "ProjectDescription", "Description", "description", "DepartmentName"),
                posted_date=parse_date(_first(p, "DateOpen", "DatePublished", "dateOpen")),
                due_date=parse_date(_first(p, "DateClose", "dateClose", "ClosingDate")),
                solicitation_id=_first(p, "ReferenceID", "referenceID", "ProjectNumber"),
            )
        )
    return out


def scrape(source: dict, fetcher: Fetcher) -> Iterable[Listing]:
    org = source["org"]
    url = (
        f"https://{org}.bonfirehub.com/PublicPortal/getOpenPublicOpportunitiesSectionData"
        f"?_={int(time.time() * 1000)}"
    )
    resp = fetcher.get(url, headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"})
    return parse_projects(resp.json(), source)
