import os
from datetime import date

import pytest

from rfp_scraper.sources import bonfire, html_page, sam_gov
from rfp_scraper.models import SourceSkipped

SRC = {"name": "City", "agency": "City of Example", "type": "html", "url": "https://city.example.gov/bids"}


def test_html_table_autodetect(fixture_text):
    items = html_page.parse_listings(fixture_text("city_bids_table.html"), SRC["url"], SRC)
    titles = [i.title for i in items]
    assert len(items) == 4, titles  # nav/footer/register links ignored
    storm = next(i for i in items if "Stormwater" in i.title)
    assert storm.url == "https://city.example.gov/docs/rfq-2026-114.pdf"
    assert storm.posted_date == date(2026, 11, 1)
    assert storm.due_date == date(2026, 12, 4)
    assert storm.solicitation_id == "2026-114"
    street = next(i for i in items if "North Avenue" in i.title)
    assert street.due_date == date(2026, 12, 15)


def test_html_cards_autodetect(fixture_text):
    items = html_page.parse_listings(fixture_text("county_cards.html"), "https://county.example.gov/", SRC)
    assert len(items) == 3
    bridge = items[0]
    assert bridge.title.startswith("Request for Qualifications: Bridge Inspection")
    assert bridge.due_date == date(2027, 1, 8)
    assert bridge.solicitation_id == "RFQ-77-2026"


def test_html_item_selector(fixture_text):
    src = dict(SRC, item_selector="table.bids tr", title_selector="td:nth-of-type(2)")
    items = html_page.parse_listings(fixture_text("city_bids_table.html"), SRC["url"], src)
    assert len(items) == 4  # header row has no link -> skipped


def test_bonfire_parse(fixture_json):
    src = {"name": "Madison", "agency": "City of Madison", "type": "bonfire", "org": "cityofmadison"}
    items = bonfire.parse_projects(fixture_json("bonfire.json"), src)
    assert len(items) == 2
    lift = items[0]
    assert lift.url == "https://cityofmadison.bonfirehub.com/opportunities/101"
    assert lift.due_date == date(2026, 12, 10)
    assert lift.solicitation_id == "11023-0-2026"


def test_sam_parse(fixture_json):
    items = sam_gov.parse_opportunities(fixture_json("sam.json"), {"name": "SAM", "agency": "Federal"})
    assert items[0].due_date == date(2026, 12, 12)
    assert items[0].agency.startswith("DEPT OF DEFENSE")
    assert "Milwaukee" in items[0].description


def test_sam_skipped_without_key(monkeypatch):
    monkeypatch.delenv("SAM_API_KEY", raising=False)
    with pytest.raises(SourceSkipped):
        sam_gov.scrape({"name": "SAM"}, fetcher=None)


def test_county_rfp_component_skips_closed_and_header_links(fixture_text):
    src = {"name": "Racine", "agency": "Racine County", "type": "html",
           "url": "https://www.racinecounty.gov/departments/finance/purchasing-rfps-and-bids"}
    items = html_page.parse_listings(fixture_text("county_rfp_component.html"), src["url"], src)
    titles = [i.title for i in items]
    # Only the open solicitation survives: sort headers, pager, closed and awarded rows are dropped.
    assert titles == ["Professional Engineering Services - CTH K Culvert and Drainage Improvements"], titles
    assert items[0].due_date == date(2026, 12, 18)
    assert items[0].url == "https://www.racinecounty.gov/Home/Components/RFP/RFP/301/26"
