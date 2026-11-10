from datetime import date

from rfp_scraper.dates import extract_dates, parse_date


def test_parse_formats():
    assert parse_date("12/04/2026") == date(2026, 12, 4)
    assert parse_date("2026-12-04") == date(2026, 12, 4)
    assert parse_date("Dec. 4, 2026 2:00 PM") == date(2026, 12, 4)
    assert parse_date("December 4th, 2026") == date(2026, 12, 4)
    assert parse_date("") is None
    assert parse_date("not a date") is None


def test_extract_labeled_dates():
    posted, due = extract_dates("RFQ 2026-114 Posted 11/01/2026 Due 12/04/2026 2:00 PM")
    assert posted == date(2026, 11, 1)
    assert due == date(2026, 12, 4)


def test_single_unlabeled_date_is_due():
    assert extract_dates("Bridge painting - 01/15/2027") == (None, date(2027, 1, 15))
