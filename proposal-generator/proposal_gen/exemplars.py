"""Exemplar retrieval and ranking (design doc section 5).

Deterministic: the same request and pool always give the same top 6.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, fields
from datetime import date

from . import config
from .models import Exemplar, ScoredExemplar

POINTS = {
    "archetype": 40,
    "archetype_alt": 15,
    "client_type": 10,
    "service_word": 5,     # each, up to 3 words
    "discipline": 6,
    "submarket": 4,
    "market": 3,
    "same_office": 3,
    "thin": -10,
}
MAX_SERVICE_WORDS = 3
SHORT_WORDS = {"hvac", "mep", "roof", "ada", "dam", "pump", "fire"}
STOP_WORDS = {
    "services", "service", "design", "designs", "engineering", "engineer", "project", "projects",
    "professional", "management", "existing", "proposed", "general", "other", "various", "additional",
    "provide", "including", "related", "support", "new",
    # v0.16.1: phase words found in almost every letter
    "construction", "documents", "administration", "drawings", "specifications", "bidding",
}
SPLIT_RE = re.compile(r"[\s;,/\-()]+")
FIELD_CAPS = {  # characters
    "project_description": 400,
    "basic_services": 2500,
    "service_phases": 200,
    "assumptions": 1000,
    "additional_services": 900,
    "client_provided": 600,
}


# ----------------------------------------------------------------- word matching

def field_words(text: str) -> list[str]:
    """Words of an exemplar field that can count as matches."""
    out = []
    for w in SPLIT_RE.split((text or "").lower()):
        w = w.strip(".:'\"&")
        if not w or w in STOP_WORDS:
            continue
        if len(w) > 4 or w in SHORT_WORDS:
            if w not in out:
                out.append(w)
    return out


def request_words(text: str) -> list[str]:
    return [w.strip(".:'\"&") for w in SPLIT_RE.split((text or "").lower()) if w.strip(".:'\"&")]


def word_found(word: str, req_words: list[str]) -> bool:
    """A word counts when a request word starts with its first 6 letters."""
    stem = word[:6]
    return any(rw.startswith(stem) for rw in req_words)


def matching_words(field: str, req_words: list[str]) -> list[str]:
    return [w for w in field_words(field) if word_found(w, req_words)]


# ----------------------------------------------------------------- scoring

def is_thin(ex: Exemplar) -> bool:
    return len((ex.basic_services or "").strip()) < config.THIN_BASIC_SERVICES


def score_exemplar(ex: Exemplar, *, archetype: str, archetype_alt: str, client_type: str,
                   services_text: str, request_text: str, office: str, today: date | None = None) -> ScoredExemplar:
    today = today or date.today()
    reasons: list[str] = []
    score = 0.0
    ex_arch = (ex.archetype or "").strip()
    if ex_arch and ex_arch == archetype:
        score += POINTS["archetype"]; reasons.append("archetype")
    elif ex_arch and archetype_alt and ex_arch == archetype_alt:
        score += POINTS["archetype_alt"]; reasons.append("alternate archetype")
    if ex.client_type and ex.client_type == client_type:
        score += POINTS["client_type"]; reasons.append("client type")

    svc_words = matching_words(ex.services, request_words(services_text))[:MAX_SERVICE_WORDS]
    if svc_words:
        score += POINTS["service_word"] * len(svc_words); reasons.append("services: " + ", ".join(svc_words))
    req = request_words(request_text)
    for key in ("discipline", "submarket", "market"):
        hit = matching_words(getattr(ex, key), req)
        if hit:
            score += POINTS[key]; reasons.append(f"{key}: {hit[0]}")
    if ex.year:
        recency = max(0, min(10, 10 - (today.year - int(ex.year))))
        score += recency
        if recency:
            reasons.append(f"recency +{recency}")
    if office and ex.office and ex.office.strip().lower() == office.strip().lower():
        score += POINTS["same_office"]; reasons.append("same office")
    thin = is_thin(ex)
    if thin:
        score += POINTS["thin"]; reasons.append("thin letter")
    return ScoredExemplar(exemplar=ex, score=score, thin=thin, reasons=reasons)


@dataclass
class Selection:
    selected: list[ScoredExemplar]
    match_mode: str           # "matched" or "pool"
    pool_count: int
    primary_count: int
    matched_count: int
    thin_in_pool: int
    fallback_reason: str = ""

    @property
    def thin_selected(self) -> int:
        return sum(1 for s in self.selected if s.thin)


def eligible_pool(rows: list[Exemplar]) -> list[Exemplar]:
    """Approved Standard-letter rows, newest first, top 100 (section 5)."""
    pool = [r for r in rows if (r.status or "").lower() == "approved"
            and "standard" in (r.letter_family or "standard").lower()]
    pool.sort(key=lambda r: (r.year or 0), reverse=True)
    return pool[: config.EXEMPLAR_POOL]


def select(pool: list[Exemplar], *, archetype: str, archetype_alt: str, client_type: str,
           confidence: str, services_text: str, request_text: str, office: str,
           today: date | None = None, limit: int | None = None) -> Selection:
    limit = limit or config.EXEMPLARS_SELECTED
    wanted = {a for a in (archetype, archetype_alt) if a and a != "other"}
    primary = [r for r in pool if r.archetype == archetype and archetype != "other"]
    matched = [r for r in pool if r.archetype in wanted]

    fallback = ""
    if not primary:
        fallback = "no approved letter has this archetype"
    elif len(matched) < 2:
        fallback = "fewer than 2 approved letters match this archetype"
    elif confidence == "low":
        fallback = "archetype confidence is low"
    candidates = pool if fallback else matched

    scored = [score_exemplar(r, archetype=archetype, archetype_alt=archetype_alt, client_type=client_type,
                             services_text=services_text, request_text=request_text, office=office, today=today)
              for r in candidates]
    # Stable tie-break: newest first, then id.
    scored.sort(key=lambda s: (-s.score, -(s.exemplar.year or 0), str(s.exemplar.id)))
    return Selection(selected=scored[:limit], match_mode="pool" if fallback else "matched",
                     pool_count=len(pool), primary_count=len(primary), matched_count=len(matched),
                     thin_in_pool=sum(1 for r in pool if is_thin(r)), fallback_reason=fallback)


# ----------------------------------------------------------------- formatting for prompts

def cap_text(text: str, cap: int) -> str:
    """Cut at the last line break inside the cap (or the last space when that
    break falls in the first half) and mark the cut with [...]."""
    text = (text or "").strip()
    if len(text) <= cap:
        return text
    head = text[:cap]
    cut = head.rfind("\n")
    if cut < cap // 2:
        cut = head.rfind(" ")
    if cut <= 0:
        cut = cap
    return head[:cut].rstrip() + " [...]"


def classifier_line(ex: Exemplar) -> str:
    return " | ".join([ex.archetype or "", ex.client_type or "", ex.services or "", (ex.why or "")[:250]])


def exemplar_block(s: ScoredExemplar) -> str:
    ex = s.exemplar
    header = (f"EXAMPLE LETTER: {ex.title} | archetype {ex.archetype} | {ex.year or ''} | {ex.office} | "
              f"{ex.discipline} | {ex.market} | services: {ex.services}")
    parts = [header, f"Project description: {cap_text(ex.project_description, FIELD_CAPS['project_description'])}"]
    if not s.thin:
        parts.append("Basic services:\n" + cap_text(ex.basic_services, FIELD_CAPS["basic_services"]))
    if (ex.service_phases or "").strip():
        parts.append("Service phases: " + cap_text(ex.service_phases, FIELD_CAPS["service_phases"]))
    parts.append("Assumptions / exclusions:\n" + cap_text(ex.assumptions, FIELD_CAPS["assumptions"]))
    parts.append("Additional services:\n" + cap_text(ex.additional_services, FIELD_CAPS["additional_services"]))
    parts.append("Client-provided:\n" + cap_text(ex.client_provided, FIELD_CAPS["client_provided"]))
    return "\n".join(parts)


# ----------------------------------------------------------------- import (CSV / Excel export of the SharePoint list)

HEADER_ALIASES = {
    "id": ["id", "item id"], "title": ["title", "name"], "status": ["status", "approval status"],
    "letter_family": ["letter family", "letterfamily", "proposal type"], "archetype": ["archetype"],
    "client_type": ["client type", "clienttype"], "services": ["services"], "why": ["why", "why it's a good example"],
    "year": ["year"], "office": ["office"], "discipline": ["discipline"], "market": ["market"],
    "submarket": ["submarket", "sub market"], "project_description": ["project description", "projectdescription"],
    "basic_services": ["basic services", "basicservices"], "service_phases": ["service phases", "servicephases"],
    "assumptions": ["assumptions", "assumptions / exclusions", "assumptions/exclusions", "exclusions"],
    "additional_services": ["additional services", "additionalservices"],
    "client_provided": ["client provided", "client-provided", "clientprovided", "client provided items"],
    "client_name": ["clientname", "client name"],
}


def _norm(h: str) -> str:
    return re.sub(r"\s+", " ", (h or "").strip().lower().replace("_", " "))


def rows_to_exemplars(header: list[str], rows: list[list]) -> list[Exemplar]:
    index = {}
    normalized = [_norm(h) for h in header]
    for field_name, aliases in HEADER_ALIASES.items():
        for i, h in enumerate(normalized):
            if h in aliases or h.replace(" ", "") in [a.replace(" ", "") for a in aliases]:
                index[field_name] = i
                break
    if "title" not in index:
        raise ValueError("The exemplar file needs at least a Title column")
    out = []
    names = {f.name for f in fields(Exemplar)}
    for n, row in enumerate(rows, start=1):
        vals = {k: ("" if row[i] is None else str(row[i]).strip()) for k, i in index.items() if i < len(row)}
        if not vals.get("title"):
            continue
        year = vals.pop("year", "")
        vals.setdefault("id", str(n))
        ex = Exemplar(**{k: v for k, v in vals.items() if k in names},
                      year=int(float(year)) if re.fullmatch(r"\d{4}(\.0)?", year or "") else None)
        out.append(ex)
    return out


def load_file(filename: str, data: bytes) -> list[Exemplar]:
    if filename.lower().endswith((".xlsx", ".xlsm")):
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb.worksheets[0]
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
    else:
        rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))
    if not rows:
        return []
    return rows_to_exemplars([str(h or "") for h in rows[0]], rows[1:])
