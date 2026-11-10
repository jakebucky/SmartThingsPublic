"""SQLite storage: RFPs (deduplicated across runs) and a log of each source run."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

from .models import Listing, Match

STATUSES = ("new", "interested", "pursuing", "dismissed")

SCHEMA = """
CREATE TABLE IF NOT EXISTS rfps (
    uid             TEXT PRIMARY KEY,
    source          TEXT NOT NULL,
    agency          TEXT,
    title           TEXT NOT NULL,
    url             TEXT NOT NULL,
    description     TEXT,
    solicitation_id TEXT,
    posted_date     TEXT,
    due_date        TEXT,
    score           INTEGER,
    categories      TEXT,
    keywords        TEXT,
    status          TEXT NOT NULL DEFAULT 'new',
    notes           TEXT,
    first_seen      TEXT NOT NULL,
    last_seen       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rfps_due ON rfps(due_date);
CREATE INDEX IF NOT EXISTS idx_rfps_status ON rfps(status);

CREATE TABLE IF NOT EXISTS source_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    listings    INTEGER DEFAULT 0,
    matched     INTEGER DEFAULT 0,
    new_matches INTEGER DEFAULT 0,
    status      TEXT,           -- ok | error | skipped
    message     TEXT
);
"""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _d(value: date | None) -> str | None:
    return value.isoformat() if value else None


def connect(path: Path | str) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def upsert_rfp(conn: sqlite3.Connection, listing: Listing, match: Match) -> bool:
    """Insert or refresh an RFP. Returns True if it was new. Keeps the user's status/notes."""
    now = _now()
    existing = conn.execute("SELECT uid FROM rfps WHERE uid = ?", (listing.uid,)).fetchone()
    values = dict(
        uid=listing.uid,
        source=listing.source,
        agency=listing.agency,
        title=listing.title,
        url=listing.url,
        description=listing.description,
        solicitation_id=listing.solicitation_id,
        posted_date=_d(listing.posted_date),
        due_date=_d(listing.due_date),
        score=match.score,
        categories=json.dumps(match.categories),
        keywords=json.dumps(match.keywords),
        now=now,
    )
    if existing:
        conn.execute(
            """UPDATE rfps SET agency=:agency, title=:title, url=:url, description=:description,
                   solicitation_id=:solicitation_id,
                   posted_date=COALESCE(:posted_date, posted_date),
                   due_date=COALESCE(:due_date, due_date),
                   score=:score, categories=:categories, keywords=:keywords, last_seen=:now
               WHERE uid=:uid""",
            values,
        )
        return False
    conn.execute(
        """INSERT INTO rfps (uid, source, agency, title, url, description, solicitation_id,
               posted_date, due_date, score, categories, keywords, first_seen, last_seen)
           VALUES (:uid, :source, :agency, :title, :url, :description, :solicitation_id,
               :posted_date, :due_date, :score, :categories, :keywords, :now, :now)""",
        values,
    )
    return True


def start_run(conn: sqlite3.Connection, source: str) -> int:
    cur = conn.execute("INSERT INTO source_runs (source, started_at) VALUES (?, ?)", (source, _now()))
    conn.commit()
    return cur.lastrowid


def finish_run(conn, run_id: int, *, status: str, listings=0, matched=0, new_matches=0, message="") -> None:
    conn.execute(
        """UPDATE source_runs SET finished_at=?, status=?, listings=?, matched=?, new_matches=?, message=?
           WHERE id=?""",
        (_now(), status, listings, matched, new_matches, message[:1000], run_id),
    )
    conn.commit()


def set_status(conn, uid: str, status: str, notes: str | None = None) -> None:
    if status not in STATUSES:
        raise ValueError(f"Invalid status: {status}")
    if notes is None:
        conn.execute("UPDATE rfps SET status=? WHERE uid=?", (status, uid))
    else:
        conn.execute("UPDATE rfps SET status=?, notes=? WHERE uid=?", (status, notes, uid))
    conn.commit()


def query_rfps(
    conn,
    *,
    q: str = "",
    category: str = "",
    source: str = "",
    status: str = "",
    include_expired: bool = False,
    sort: str = "due",
) -> list[dict]:
    where, params = [], []
    if q:
        where.append("(title LIKE ? OR description LIKE ? OR agency LIKE ? OR solicitation_id LIKE ?)")
        params += [f"%{q}%"] * 4
    if category:
        where.append("categories LIKE ?")
        params.append(f'%"{category}"%')
    if source:
        where.append("source = ?")
        params.append(source)
    if status == "active":
        where.append("status != 'dismissed'")
    elif status:
        where.append("status = ?")
        params.append(status)
    if not include_expired:
        where.append("(due_date IS NULL OR due_date >= ?)")
        params.append(date.today().isoformat())
    order = {
        "due": "due_date IS NULL, due_date ASC, score DESC",
        "score": "score DESC, due_date ASC",
        "newest": "first_seen DESC, score DESC",
    }.get(sort, "due_date IS NULL, due_date ASC")
    sql = "SELECT * FROM rfps"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += f" ORDER BY {order}"
    rows = []
    for r in conn.execute(sql, params):
        d = dict(r)
        d["categories"] = json.loads(d["categories"] or "[]")
        d["keywords"] = json.loads(d["keywords"] or "[]")
        rows.append(d)
    return rows


def latest_runs(conn) -> list[dict]:
    sql = """SELECT r.* FROM source_runs r
             JOIN (SELECT source, MAX(id) AS id FROM source_runs GROUP BY source) m ON r.id = m.id
             ORDER BY r.source"""
    return [dict(r) for r in conn.execute(sql)]


def last_run_started(conn) -> str | None:
    row = conn.execute("SELECT MIN(started_at) FROM source_runs WHERE id IN "
                       "(SELECT MAX(id) FROM source_runs GROUP BY source)").fetchone()
    return row[0] if row else None
