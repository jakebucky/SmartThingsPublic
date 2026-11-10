"""Pull posted / due dates out of free text like 'Proposals due: Dec. 5, 2026 2:00 PM'."""
from __future__ import annotations

import re
from datetime import date, datetime

from dateutil import parser as dtparser

_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
DATE_RE = re.compile(
    rf"\b(?:\d{{1,2}}/\d{{1,2}}/\d{{2,4}}"  # 12/05/2026
    rf"|\d{{4}}-\d{{2}}-\d{{2}}"  # 2026-12-05
    rf"|{_MONTH}\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}})",  # December 5, 2026
    re.IGNORECASE,
)

DUE_WORDS = re.compile(
    r"\b(due|deadline|clos(?:e|es|ing)|opening|bid open|submittals?|responses?|proposals? (?:are )?due)\b",
    re.IGNORECASE,
)
POSTED_WORDS = re.compile(r"\b(posted|issued|issue date|released?|published|advertised)\b", re.IGNORECASE)


def parse_date(text: str | None) -> date | None:
    if not text:
        return None
    text = text.strip()
    if not text:
        return None
    m = DATE_RE.search(text)
    candidate = m.group(0) if m else text
    try:
        dt = dtparser.parse(candidate, fuzzy=True, default=datetime(2000, 1, 1))
    except (ValueError, OverflowError, TypeError):
        return None
    if dt.year < 2000 or dt.year > 2100:
        return None
    return dt.date()


def extract_dates(text: str) -> tuple[date | None, date | None]:
    """Return (posted_date, due_date) guessed from the words just before each date."""
    posted = due = None
    unlabeled: list[date] = []
    for m in DATE_RE.finditer(text):
        d = parse_date(m.group(0))
        if d is None:
            continue
        before = text[max(0, m.start() - 40): m.start()]
        if DUE_WORDS.search(before) and due is None:
            due = d
        elif POSTED_WORDS.search(before) and posted is None:
            posted = d
        else:
            unlabeled.append(d)
    # One unlabeled date on a bid listing is almost always the due date.
    if due is None and unlabeled:
        due = max(unlabeled)
    return posted, due
