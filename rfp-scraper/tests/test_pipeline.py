"""End to end: runner -> database -> dashboard, with HTTP replaced by local fixtures."""
from datetime import date

from rfp_scraper import db, runner
from rfp_scraper.web.app import create_app


class FakeResponse:
    def __init__(self, text, url):
        self.text, self.url, self.headers = text, url, {"Content-Type": "text/html"}

    def json(self):
        import json
        return json.loads(self.text)


class FakeFetcher:
    def __init__(self, pages):
        self.pages = pages

    def get(self, url, **kwargs):
        for prefix, text in self.pages.items():
            if url.startswith(prefix):
                return FakeResponse(text, url)
        raise ConnectionError(f"blocked: {url}")


def sources():
    return [
        {"name": "City", "agency": "City of Example", "agency_type": "City", "type": "html", "url": "https://city.example.gov/bids", "enabled": True},
        {"name": "County", "agency": "Example County", "agency_type": "County", "type": "html", "url": "https://county.example.gov/", "enabled": True},
        {"name": "Madison", "agency": "City of Madison", "type": "bonfire", "org": "cityofmadison", "enabled": True},
        {"name": "Broken", "agency": "Nowhere", "type": "html", "url": "https://broken.example.gov/", "enabled": True},
        {"name": "Off", "agency": "Off", "type": "html", "url": "https://off.example.gov/", "enabled": False},
    ]


def make_fetcher(fixture_text):
    return FakeFetcher({
        "https://city.example.gov": fixture_text("city_bids_table.html"),
        "https://county.example.gov": fixture_text("county_cards.html"),
        "https://cityofmadison.bonfirehub.com": fixture_text("bonfire.json"),
    })


def test_run_stores_only_relevant_and_dedupes(tmp_path, keywords, fixture_text):
    conn = db.connect(tmp_path / "t.db")
    s = runner.run(conn, sources(), keywords, fetcher=make_fetcher(fixture_text))
    assert s.sources == 4
    assert len(s.errors) == 1 and "Broken" in s.errors[0]
    titles = {r["title"] for r in db.query_rfps(conn, include_expired=True)}
    assert any("Stormwater" in t for t in titles)
    assert any("Bridge Inspection" in t for t in titles)
    assert any("Lift Station" in t for t in titles)
    assert any("Master Plan" in t for t in titles)
    assert not any("Janitorial" in t or "Insurance" in t or "Office Supplies" in t or "Fleet" in t for t in titles)

    # Second run: nothing new, user status preserved.
    rfp = db.query_rfps(conn, include_expired=True)[0]
    db.set_status(conn, rfp["uid"], "interested", "call PM")
    s2 = runner.run(conn, sources(), keywords, fetcher=make_fetcher(fixture_text))
    assert s2.new == 0 and s2.matched == s.matched
    again = next(r for r in db.query_rfps(conn, include_expired=True) if r["uid"] == rfp["uid"])
    assert again["status"] == "interested" and again["notes"] == "call PM"


def test_dashboard(tmp_path, keywords, fixture_text, monkeypatch):
    path = tmp_path / "t.db"
    conn = db.connect(path)
    runner.run(conn, sources(), keywords, fetcher=make_fetcher(fixture_text))
    conn.close()

    from rfp_scraper import config
    monkeypatch.setattr(config, "load_sources", sources)
    app = create_app(db_path=path)
    client = app.test_client()

    page = client.get("/?expired=1").get_data(as_text=True)
    assert "Stormwater Management Plan" in page
    assert "Janitorial" not in page

    page = client.get("/?expired=1&category=Structural").get_data(as_text=True)
    assert "Bridge Inspection" in page and "Stormwater" not in page

    page = client.get("/?expired=1&agency_type=County").get_data(as_text=True)
    assert "Bridge Inspection" in page and "Stormwater" not in page
    assert "All agency types" in page

    page = client.get("/sources").get_data(as_text=True)
    assert "Broken" in page and "error" in page

    csv = client.get("/export.csv?expired=1").get_data(as_text=True)
    assert csv.splitlines()[0].startswith("Due date,Title")

    uid = db.query_rfps(db.connect(path), include_expired=True)[0]["uid"]
    r = client.post(f"/rfp/{uid}/status", data={"status": "dismissed"})
    assert r.status_code == 302
    page = client.get("/?expired=1").get_data(as_text=True)
    assert page.count('class="rfp ') == len(db.query_rfps(db.connect(path), include_expired=True)) - 1


def test_expired_hidden_by_default(tmp_path):
    from rfp_scraper.models import Listing, Match
    conn = db.connect(tmp_path / "t.db")
    old = Listing("s", "a", "Old bridge RFP", "http://x/1", due_date=date(2020, 1, 1))
    db.upsert_rfp(conn, old, Match(score=3))
    assert db.query_rfps(conn) == []
    assert len(db.query_rfps(conn, include_expired=True)) == 1


def test_agency_type_stored(tmp_path, keywords, fixture_text):
    conn = db.connect(tmp_path / "t.db")
    runner.run(conn, sources(), keywords, fetcher=make_fetcher(fixture_text))
    county = db.query_rfps(conn, include_expired=True, agency_type="County")
    assert county and all(r["agency"] == "Example County" for r in county)


def test_migrates_old_database(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.execute("""CREATE TABLE rfps (uid TEXT PRIMARY KEY, source TEXT NOT NULL, agency TEXT,
        title TEXT NOT NULL, url TEXT NOT NULL, description TEXT, solicitation_id TEXT,
        posted_date TEXT, due_date TEXT, score INTEGER, categories TEXT, keywords TEXT,
        status TEXT NOT NULL DEFAULT 'new', notes TEXT, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL)""")
    old.commit(); old.close()
    conn = db.connect(path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(rfps)")}
    assert "agency_type" in cols
