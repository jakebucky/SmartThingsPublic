"""Bid-alert emails (e.g. DemandStar / Euna OpenBids notifications).

Many Wisconsin agencies post formal solicitations only on DemandStar. Instead
of scraping DemandStar (no public API, and its terms of service restrict
automated access), register a vendor account there, choose commodity codes /
agencies, and let it email you alerts. This source reads those emails:

  mode: imap    - read a mailbox folder over IMAP (SSL)
      host            imap.gmail.com, outlook.office365.com, ...
      username_env    env var holding the login      (default RFP_IMAP_USER)
      password_env    env var holding the password   (default RFP_IMAP_PASSWORD)
                      (for Gmail/Microsoft 365 use an app password)
      folder          mailbox folder (default INBOX)
      from_filter     only emails whose sender contains this (default demandstar)
      days_back       how far back to read (default 30)

  mode: folder  - read saved .eml / .txt / .html files from a directory
      path            directory (relative paths are relative to the project)

The email layout isn't hard-coded: each bid is found as a titled link, and the
text between it and the next bid link is searched for the agency, solicitation
number and dates. Matching against GRAEF keywords happens later as usual.
"""
from __future__ import annotations

import email
import imaplib
import os
import re
from datetime import date, timedelta
from email.message import Message
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from ..config import PROJECT_DIR
from ..dates import extract_dates
from ..fetch import Fetcher
from ..models import Listing, SourceSkipped

MARK = "⁣LINK{}⁣"
MARK_RE = re.compile("⁣LINK(\\d+)⁣")
URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")

JUNK_LINK_RE = re.compile(
    r"unsubscribe|view (?:this|in) (?:email|browser)|privacy|terms|preferences|manage|"
    r"log ?in|sign ?in|my account|help|support|contact us|forward|facebook|twitter|linkedin|"
    r"update your|commodity codes?|upgrade|subscription|download the app",
    re.IGNORECASE,
)
LABEL_LINE_RE = re.compile(r"^\s*[A-Za-z][A-Za-z /#.]{1,30}:\s*")
AGENCY_RE = re.compile(
    r"^\s*(?:agency|issuing agency|agency name|organization|buyer|government|entity)\s*[:\-]\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
BID_ID_RE = re.compile(
    r"\b(?:bid|solicitation|rfp|rfq|rfb|ifb|itb)\s*(?:number|no\.?|id|#)\s*[:#]?\s*([A-Z0-9][\w\-/.]{2,})",
    re.IGNORECASE,
)


def agency_type_for(agency: str) -> str:
    a = agency.lower()
    if "technical college" in a or re.search(r"\bcollege\b", a):
        return "Technical College"
    if "school" in a or "unified" in a or re.search(r"\bsd\b|\bisd\b", a):
        return "School District"
    if "county" in a:
        return "County"
    if re.search(r"\b(city|village|town)\b", a):
        return "City"
    if "sewerage" in a or "utilit" in a or "water" in a:
        return "Utility"
    if "state of" in a or "department of" in a or "wisconsin dep" in a:
        return "State"
    return ""


# ----------------------------------------------------------------- parsing

def _segments_from_html(html: str) -> list[tuple[str, str, str]]:
    """Return (link_text, href, following_text) for each candidate bid link."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "head"]):
        tag.decompose()
    links = []
    for a in soup.find_all("a", href=True):
        text = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
        href = a["href"].strip()
        if not href.lower().startswith("http") or len(text) < 12 or JUNK_LINK_RE.search(text):
            continue
        a.replace_with(soup.new_string("\n" + MARK.format(len(links)) + "\n"))
        links.append((text, href))
    text = soup.get_text("\n")
    return _split_on_marks(text, links)


def _split_on_marks(text: str, links: list[tuple[str, str]]) -> list[tuple[str, str, str]]:
    parts = MARK_RE.split(text)
    # parts = [before, idx0, after0, idx1, after1, ...]
    out = []
    for i in range(1, len(parts), 2):
        title, href = links[int(parts[i])]
        context = parts[i + 1] if i + 1 < len(parts) else ""
        out.append((title, href, context))
    return out


def _segments_from_text(text: str) -> list[tuple[str, str, str]]:
    """Plain-text alerts: each bid is a block containing a URL."""
    out = []
    for block in re.split(r"\n\s*\n", text):
        m = URL_RE.search(block)
        if not m:
            continue
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        title = next(
            (ln for ln in lines if not URL_RE.search(ln) and not LABEL_LINE_RE.match(ln) and len(ln) >= 12),
            "",
        )
        if not title or JUNK_LINK_RE.search(title):
            continue
        context = "\n".join(ln for ln in lines if ln != title)
        out.append((title, m.group(0), context))
    return out


def _clean(s: str) -> str:
    return re.sub(r"[ \t\r\f\v]+", " ", re.sub(r"\n\s*\n+", "\n", s)).strip()


def parse_body(body: str, is_html: bool, source: dict, received: date | None = None) -> list[Listing]:
    segments = _segments_from_html(body) if is_html else _segments_from_text(body)
    default_agency = source.get("agency", "DemandStar")
    listings = []
    seen = set()
    for title, href, context in segments:
        context = _clean(context)[:1500]
        posted, due = extract_dates(context)
        if not (posted or due or BID_ID_RE.search(context) or "demandstar" in urlparse(href).netloc.lower()):
            continue  # a link with no bid details next to it (e.g. a banner)
        m = AGENCY_RE.search(context)
        agency = m.group(1).strip() if m else default_agency
        idm = BID_ID_RE.search(context)
        key = (href, title.lower())
        if key in seen:
            continue
        seen.add(key)
        listings.append(
            Listing(
                source=source["name"],
                agency=agency[:200],
                agency_type=agency_type_for(agency) if m else source.get("agency_type", ""),
                title=title[:300],
                url=href,
                description=context.replace("\n", " · "),
                posted_date=posted or received,
                due_date=due,
                solicitation_id=idm.group(1).rstrip(".") if idm else "",
            )
        )
    return listings


def _body(msg: Message) -> tuple[str, bool]:
    html = text = None
    for part in msg.walk() if msg.is_multipart() else [msg]:
        if part.get_content_maintype() == "multipart" or part.get_filename():
            continue
        ctype = part.get_content_type()
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        decoded = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        if ctype == "text/html" and html is None:
            html = decoded
        elif ctype == "text/plain" and text is None:
            text = decoded
    if html:
        return html, True
    return text or "", False


def parse_message(msg: Message, source: dict) -> list[Listing]:
    received = None
    if msg.get("Date"):
        try:
            received = parsedate_to_datetime(msg["Date"]).date()
        except (TypeError, ValueError):
            pass
    body, is_html = _body(msg)
    return parse_body(body, is_html, source, received)


# ----------------------------------------------------------------- inputs

def _from_folder(source: dict) -> Iterable[Message | tuple[str, bool]]:
    path = Path(source.get("path", "data/alerts"))
    if not path.is_absolute():
        path = PROJECT_DIR / path
    if not path.is_dir():
        raise SourceSkipped(f"folder {path} does not exist")
    for f in sorted(path.iterdir()):
        suffix = f.suffix.lower()
        if suffix == ".eml":
            yield email.message_from_bytes(f.read_bytes())
        elif suffix in (".html", ".htm"):
            yield f.read_text(errors="replace"), True
        elif suffix == ".txt":
            yield f.read_text(errors="replace"), False


def _from_imap(source: dict, imap_factory=imaplib.IMAP4_SSL) -> Iterable[Message]:
    user = os.environ.get(source.get("username_env", "RFP_IMAP_USER"))
    password = os.environ.get(source.get("password_env", "RFP_IMAP_PASSWORD"))
    host = source.get("host")
    if not (host and user and password):
        raise SourceSkipped("IMAP host, username or password not configured")
    since = (date.today() - timedelta(days=int(source.get("days_back", 30)))).strftime("%d-%b-%Y")
    criteria = ["SINCE", since]
    if source.get("from_filter", "demandstar"):
        criteria += ["FROM", f'"{source.get("from_filter", "demandstar")}"']
    conn = imap_factory(host, int(source.get("port", 993)))
    try:
        conn.login(user, password)
        conn.select(f'"{source.get("folder", "INBOX")}"', readonly=True)
        status, data = conn.search(None, *criteria)
        if status != "OK":
            raise RuntimeError(f"IMAP search failed: {status}")
        for num in (data[0] or b"").split():
            status, parts = conn.fetch(num, "(BODY.PEEK[])")
            if status == "OK" and parts and isinstance(parts[0], tuple):
                yield email.message_from_bytes(parts[0][1])
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def scrape(source: dict, fetcher: Fetcher | None = None) -> Iterable[Listing]:
    mode = source.get("mode", "folder")
    if mode == "imap":
        items = _from_imap(source)
    elif mode == "folder":
        items = _from_folder(source)
    else:
        raise ValueError(f"email_alerts mode must be 'imap' or 'folder', not {mode!r}")

    listings: list[Listing] = []
    for item in items:
        if isinstance(item, tuple):
            listings.extend(parse_body(item[0], item[1], source))
        else:
            listings.extend(parse_message(item, source))
    return listings
