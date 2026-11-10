"""Generic scraper for an agency's 'Bids & RFPs' web page.

Without configuration it finds listings by looking for links whose surrounding
block (table row, list item, card) mentions solicitation wording such as
RFP, RFQ, bid, or request for proposals. A source can instead give an explicit
`item_selector` (and optional `title_selector`) when auto-detection is noisy.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Iterable
from urllib.parse import urljoin, urldefrag

from bs4 import BeautifulSoup, Tag

from ..dates import extract_dates
from ..fetch import Fetcher
from ..models import Listing

SOLICITATION_RE = re.compile(
    r"\b(rfp|rfq|rfi|rfb|ifb|itb|request(?:s)? for (?:proposals?|qualifications|bids?|information)"
    r"|invitation (?:to|for) bids?|solicitations?|bids?|proposals?|qualifications|letting)\b",
    re.IGNORECASE,
)
SOLICITATION_ID_RE = re.compile(
    r"\b(?:(?:rfp|rfq|rfb|ifb|itb|bid|solicitation|project)\s*(?:no\.?|number|#)?\s*[:#]?\s*)"
    r"([A-Z0-9][A-Z0-9\-_.]{2,})\b",
    re.IGNORECASE,
)
CLOSED_RE = re.compile(r"\b(closed|awarded|cancell?ed|rescinded|archived)\b", re.IGNORECASE)
CONTAINER_TAGS = ("tr", "li", "article", "dd", "p")
SKIP_ANCESTORS = ("nav", "header", "footer")
MAX_BLOCK_CHARS = 1200
# Links that are site chrome, not listings.
JUNK_LINK_RE = re.compile(
    r"^(home|contact|login|log in|sign in|register|search|menu|back|more|next|previous|faq|help|"
    r"vendor registration|how to (?:bid|register).*)$",
    re.IGNORECASE,
)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _block_for(link: Tag) -> Tag:
    """The smallest sensible container around a link (row, list item, card)."""
    link_len = len(link.get_text(" ", strip=True))
    for parent in link.parents:
        if not isinstance(parent, Tag):
            continue
        if parent.name in CONTAINER_TAGS:
            return parent
        if parent.name in ("div", "section"):
            text_len = len(parent.get_text(" ", strip=True))
            if text_len > MAX_BLOCK_CHARS or len(parent.find_all("a")) > 4:
                break  # too big to be one listing; stop climbing
            if text_len > link_len + 15:
                return parent  # a small "card" with extra context (dates, ids)
        if parent.name in ("body", "html", "main", "table", "ul", "ol"):
            break
    return link


def _in_chrome(link: Tag) -> bool:
    for parent in link.parents:
        if isinstance(parent, Tag):
            if parent.name in SKIP_ANCESTORS:
                return True
            role = (parent.get("role") or "").lower()
            if role in ("navigation", "banner", "contentinfo"):
                return True
    return False


def _solicitation_id(text: str) -> str:
    m = SOLICITATION_ID_RE.search(text)
    if m and any(ch.isdigit() for ch in m.group(1)):
        return m.group(1).rstrip(".")
    return ""


def parse_listings(html: str, base_url: str, source: dict) -> list[Listing]:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    listings: list[Listing] = []
    seen: set[str] = set()

    # On a page titled e.g. "Purchasing RFPs and Bids", rows of the listing table
    # often don't repeat the word RFP; a dated row there is enough.
    heading = " ".join(
        _clean(t.get_text(" ", strip=True)) for t in soup.find_all(["title", "h1", "h2"])[:6]
    )
    page_is_bid_list = bool(SOLICITATION_RE.search(heading))

    item_selector = source.get("item_selector")
    title_selector = source.get("title_selector")

    if item_selector:
        blocks = [(b, b.find("a", href=True)) for b in soup.select(item_selector)]
    else:
        blocks = []
        for a in soup.find_all("a", href=True):
            if _in_chrome(a):
                continue
            blocks.append((_block_for(a), a))

    for block, link in blocks:
        if link is None:
            continue
        href = link.get("href", "").strip()
        if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        url = urldefrag(urljoin(base_url, href))[0]

        block_text = _clean(block.get_text(" ", strip=True))
        link_text = _clean(link.get_text(" ", strip=True)) or _clean(link.get("title", ""))
        if title_selector:
            t = block.select_one(title_selector)
            title = _clean(t.get_text(" ", strip=True)) if t else link_text
        else:
            title = link_text if len(link_text) >= 12 else block_text[:200]

        if not title or JUNK_LINK_RE.match(title):
            continue
        if len(block_text) > MAX_BLOCK_CHARS:
            block_text = block_text[:MAX_BLOCK_CHARS]
        posted, due = extract_dates(block_text)
        sol_id = _solicitation_id(block_text)
        if not item_selector:
            in_bid_list = (
                page_is_bid_list
                and block.name in ("tr", "li")
                and (posted or due)
                and len(link_text) >= 12
            )
            if not SOLICITATION_RE.search(block_text) and not in_bid_list:
                continue
            # Boilerplate like "Vendors must register to receive bid notices" mentions
            # bids but isn't one: a real listing names the solicitation in its link
            # text, or carries a date / solicitation number next to it.
            if not (SOLICITATION_RE.search(link_text) and len(link_text) >= 12) and not (posted or due or sol_id):
                continue

        # Many county pages keep past solicitations on the same list, marked
        # "Closed" / "Awarded". Drop those unless they show a future due date.
        status_text = block_text.replace(title, " ")
        if CLOSED_RE.search(status_text) and not (due and due >= date.today()):
            continue

        key = f"{url}|{title.lower()}"
        if key in seen:
            continue
        seen.add(key)

        listings.append(
            Listing(
                source=source["name"],
                agency=source.get("agency", source["name"]),
                title=title[:300],
                url=url,
                description=block_text if block_text != title else "",
                posted_date=posted,
                due_date=due,
                solicitation_id=sol_id,
            )
        )
    return listings


def detail_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer"]):
        tag.decompose()
    main = soup.find("main") or soup.find(id=re.compile("content|main", re.I)) or soup.body or soup
    return _clean(main.get_text(" ", strip=True))[:8000]


def scrape(source: dict, fetcher: Fetcher) -> Iterable[Listing]:
    resp = fetcher.get(source["url"])
    listings = parse_listings(resp.text, resp.url, source)

    if source.get("fetch_details"):
        limit = int(source.get("max_details", 40))
        for listing in listings[:limit]:
            if listing.url.lower().endswith((".pdf", ".doc", ".docx", ".zip")):
                continue
            try:
                r = fetcher.get(listing.url)
            except Exception:
                continue
            if "html" not in r.headers.get("Content-Type", "html"):
                continue
            text = detail_text(r.text)
            listing.description = _clean(f"{listing.description} {text}")[:8000]
            posted, due = extract_dates(text)
            listing.posted_date = listing.posted_date or posted
            listing.due_date = listing.due_date or due
    return listings
