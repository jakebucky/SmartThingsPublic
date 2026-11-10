"""Sanity checks on the shipped config so a typo doesn't silently drop a source."""
from urllib.parse import urlparse

from rfp_scraper import config
from rfp_scraper.matcher import Matcher
from rfp_scraper.sources import REGISTRY

AGENCY_TYPES = {"State", "City", "County", "School District", "Technical College", "Utility", "Federal"}


def test_sources_are_valid():
    sources = config.load_sources()
    names = [s["name"] for s in sources]
    assert len(names) == len(set(names)), "duplicate source names"
    for s in sources:
        assert s["type"] in REGISTRY, s
        if s["type"] != "email_alerts":  # alert emails carry the agency per bid
            assert s.get("agency_type") in AGENCY_TYPES, s
        if s["type"] == "html":
            u = urlparse(s["url"])
            assert u.scheme == "https" and u.netloc, s
        if s["type"] == "bonfire":
            assert s.get("org"), s


def test_coverage_includes_counties_and_schools():
    types = [s["agency_type"] for s in config.load_sources()]
    assert types.count("County") >= 10
    assert types.count("School District") >= 5


def test_keywords_compile():
    Matcher(config.load_keywords())
