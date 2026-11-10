from rfp_scraper.matcher import Matcher
from rfp_scraper.models import Listing


def L(title, desc=""):
    return Listing(source="t", agency="t", title=title, url="http://x", description=desc)


def test_relevant_engineering_rfq(keywords):
    ok, m = Matcher(keywords).is_relevant(L("RFQ: Professional Engineering Services for Stormwater Plan"))
    assert ok
    assert "Water Resources" in m.categories
    assert "stormwater" in m.keywords


def test_excluded(keywords):
    ok, m = Matcher(keywords).is_relevant(L("Janitorial services for engineering building"))
    assert not ok and m.excluded_by == "janitorial"


def test_generic_word_alone_not_enough(keywords):
    ok, _ = Matcher(keywords).is_relevant(L("Consultant for HR training"))
    assert not ok


def test_whole_words_only(keywords):
    # "dam" must not match inside "Amsterdam" / "damage"; "trail" not inside "trailer"
    ok, m = Matcher(keywords).is_relevant(L("Trailer purchase and damage repair"))
    assert not ok, m.keywords


def test_plural_matches(keywords):
    _, m = Matcher(keywords).is_relevant(L("Replacement of two bridges"))
    assert "bridge" in m.keywords
