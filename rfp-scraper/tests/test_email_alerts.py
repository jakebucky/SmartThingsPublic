import email
import shutil
from datetime import date

import pytest

from rfp_scraper.matcher import Matcher
from rfp_scraper.models import SourceSkipped
from rfp_scraper.sources import email_alerts

SRC = {"name": "DemandStar Alerts", "agency": "DemandStar", "type": "email_alerts"}


def test_parse_html_alert(fixture_text):
    msg = email.message_from_string(fixture_text("alert_html.eml"))
    items = email_alerts.parse_message(msg, SRC)
    assert [i.title for i in items] == [
        "Professional Engineering Services for Lift Station No. 4 Replacement",
        "Custodial Supplies Annual Contract",
        "CTH A Bridge Replacement Design and Construction Engineering Services",
    ]  # login / unsubscribe / preferences links ignored
    lift = items[0]
    assert lift.agency == "Racine Unified School District"
    assert lift.agency_type == "School District"
    assert lift.solicitation_id == "RFQ-27-0012-0-2026/PL"
    assert lift.posted_date == date(2026, 11, 6)
    assert lift.due_date == date(2026, 12, 8)
    assert lift.url == "https://click.example.net/ls/click?u=abc1"
    assert items[2].agency_type == "County"
    assert items[2].due_date == date(2027, 1, 12)


def test_parse_text_alert(fixture_text):
    items = email_alerts.parse_body(fixture_text("alert_text.txt"), False, SRC)
    assert [i.title for i in items] == [
        "Stormwater Pond Retrofit Design Services - Elmbrook Park",
        "Food Service Equipment Replacement",
    ]
    assert items[0].agency == "Elmbrook School District"
    assert items[0].due_date == date(2026, 12, 15)
    assert items[0].url.endswith("/bid/111")


def test_keywords_filter_alerts(fixture_text, keywords):
    msg = email.message_from_string(fixture_text("alert_html.eml"))
    m = Matcher(keywords)
    kept = [i.title for i in email_alerts.parse_message(msg, SRC) if m.is_relevant(i)[0]]
    assert len(kept) == 2 and not any("Custodial" in t for t in kept)


def test_folder_mode(tmp_path, fixture_text):
    from pathlib import Path
    fx = Path(__file__).parent / "fixtures"
    shutil.copy(fx / "alert_html.eml", tmp_path / "a.eml")
    shutil.copy(fx / "alert_text.txt", tmp_path / "b.txt")
    (tmp_path / "ignore.pdf").write_bytes(b"%PDF")
    items = list(email_alerts.scrape(dict(SRC, mode="folder", path=str(tmp_path))))
    assert len(items) == 5


def test_folder_missing_is_skipped(tmp_path):
    with pytest.raises(SourceSkipped):
        list(email_alerts.scrape(dict(SRC, mode="folder", path=str(tmp_path / "nope"))))


def test_imap_requires_credentials(monkeypatch):
    monkeypatch.delenv("RFP_IMAP_USER", raising=False)
    monkeypatch.delenv("RFP_IMAP_PASSWORD", raising=False)
    with pytest.raises(SourceSkipped):
        list(email_alerts.scrape(dict(SRC, mode="imap", host="imap.example.com")))


def test_imap_mode(monkeypatch, fixture_text):
    raw = fixture_text("alert_html.eml").encode()
    calls = {}

    class FakeIMAP:
        def __init__(self, host, port):
            calls["host"] = (host, port)

        def login(self, u, p):
            calls["login"] = (u, p)

        def select(self, folder, readonly):
            calls["select"] = (folder, readonly)

        def search(self, charset, *criteria):
            calls["criteria"] = criteria
            return "OK", [b"1 2"]

        def fetch(self, num, what):
            calls.setdefault("fetched", []).append((num, what))
            return "OK", [(b"1 (BODY[] {123}", raw), b")"]

        def logout(self):
            calls["logout"] = True

    monkeypatch.setenv("RFP_IMAP_USER", "bids@example.com")
    monkeypatch.setenv("RFP_IMAP_PASSWORD", "app-password")
    src = dict(SRC, mode="imap", host="imap.example.com", folder="Bids", from_filter="demandstar")
    msgs = list(email_alerts._from_imap(src, imap_factory=FakeIMAP))
    assert len(msgs) == 2
    assert calls["select"] == ('"Bids"', True)  # read-only: never marks mail as read
    assert "FROM" in calls["criteria"] and '"demandstar"' in calls["criteria"]
    assert all(w == "(BODY.PEEK[])" for _, w in calls["fetched"])
    assert calls["logout"]


@pytest.mark.parametrize("agency,expected", [
    ("Rock County", "County"),
    ("Racine Unified School District", "School District"),
    ("Milwaukee Area Technical College", "Technical College"),
    ("City of Janesville", "City"),
    ("Village of Pewaukee", "City"),
    ("Some Agency", ""),
])
def test_agency_type_for(agency, expected):
    assert email_alerts.agency_type_for(agency) == expected
