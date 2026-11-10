# RFP Finder

Checks Wisconsin public-sector websites (state, county, city, school district,
sewerage district, plus federal opportunities in Wisconsin) for RFPs / RFQs that
match GRAEF's engineering services, and shows them in a web dashboard.

## Quick start

```bash
cd rfp-scraper
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python -m rfp_scraper scrape -v    # check every source now
python -m rfp_scraper serve        # open http://127.0.0.1:5000
```

The dashboard also has a **Run scrape now** button.

## Coverage

| Type | Sources |
|---|---|
| State | VendorNet, WisDOT consultant selection, DOA Division of Facilities Development |
| Cities & utilities | City of Milwaukee (DPW + Purchasing), City of Madison (Bonfire), MMSD |
| Counties | Milwaukee, Waukesha, Dane (Public Works + Purchasing), Racine, Ozaukee, Washington, Brown, Outagamie, Marathon, Eau Claire |
| School districts | Milwaukee Public Schools, Madison Metropolitan (2 pages), Kenosha Unified, Appleton Area, Milton |
| Technical colleges | Madison College |
| Federal | SAM.gov opportunities in WI (needs `SAM_API_KEY`) |

The dashboard can filter by agency type (County, School District and so on).

**Not covered yet:** these agencies post formal solicitations only on
DemandStar (Euna OpenBids) or OpenGov: Rock, La Crosse, Walworth, Kenosha,
Sheboygan and Winnebago counties; Racine Unified, Green Bay, Oshkosh, Eau Claire,
Waukesha, Elmbrook, Sun Prairie, Verona, Middleton-Cross Plains, Janesville and
West Allis-West Milwaukee school districts; and MATC. A DemandStar adapter
would pick up most of them at once (see the bottom of `config/sources.yaml`).

## What it does

1. **Collects listings** from each source in `config/sources.yaml`:
   - `html`: any public "Bids / RFPs" page. Listings are auto-detected
     (links whose row or card mentions RFP, RFQ, bid, solicitation and so on,
     plus a date or number), with optional CSS selectors for tricky pages.
   - `bonfire`: agencies on `<org>.bonfirehub.com` (for example, City of Madison).
   - `sam_gov`: federal opportunities in WI by NAICS code (541330 Engineering,
     541320 Landscape Architecture, 541370 Surveying, 541310 Architecture).
     Needs a free API key: `export SAM_API_KEY=...`.
2. **Scores each listing** against `config/keywords.yaml`: service categories
   (Transportation, Structural, Water Resources, Civil/Site, Landscape
   Architecture & Planning, Survey), boosts for RFQ/qualifications wording, and
   exclusions (janitorial, insurance and so on). Only listings at or above
   `min_score` are kept.
3. **Stores** them in `data/rfps.db` (SQLite), deduplicated across runs, with
   posted and due dates and the solicitation number when found.
4. **Dashboard**: search; filter by service, source and status; sort by due
   date, match score or newest; mark each RFP *Interested*, *Pursuing* or
   *Dismissed*; export to CSV. The **Sources** tab shows each site's last
   result so broken sources are easy to spot.

It identifies itself with a User-Agent, obeys `robots.txt`, and waits
1.5 seconds between requests to the same site.

## Tuning

- **Fix or add a site:** edit `config/sources.yaml`. If auto-detection picks up
  junk or misses listings, add `item_selector` (CSS for one listing, such as
  `table.bids tr`) and optionally `title_selector`. Set `fetch_details: true` to
  read each listing's own page for better keyword matching.
- **Change what counts as relevant:** edit `config/keywords.yaml`.

The URLs in `sources.yaml` are starting points and were not checked live (the
build environment had no access to these sites). After the first run, look at
the Sources tab and fix any source that shows an error or 0 listings.

## Running it on a schedule

Run `python -m rfp_scraper scrape` daily with cron (macOS/Linux) or Task Scheduler (Windows), e.g.

```
0 7 * * 1-5  cd /path/to/rfp-scraper && .venv/bin/python -m rfp_scraper scrape
```

## Tests

```bash
python -m pytest -q
```

Tests use saved sample pages in `tests/fixtures/` and make no network calls.

## Known limits / next steps

- DemandStar / OpenGov / QuestCDN / Bid Express listings aren't scraped yet
  (see "Not covered yet" above). Adding one requires checking that the site's
  terms allow automated access.
- PDF attachments are linked but not read.
- Sites that render listings with JavaScript (other than Bonfire) need a
  browser-based adapter (e.g. Playwright).
