"""Command line: `python -m rfp_scraper scrape` / `serve` / `list`."""
from __future__ import annotations

import argparse
import logging
import sys

from . import config, db, runner


def cmd_scrape(args) -> int:
    conn = db.connect(args.db)
    summary = runner.run(conn, config.load_sources(), config.load_keywords(), only=args.source)
    print(
        f"Checked {summary.sources} sources: {summary.listings} listings, "
        f"{summary.matched} relevant, {summary.new} new."
    )
    for err in summary.errors:
        print(f"  ! {err}", file=sys.stderr)
    return 0


def cmd_list(args) -> int:
    conn = db.connect(args.db)
    rows = db.query_rfps(conn, status="active", sort=args.sort)
    if not rows:
        print("No open RFPs stored yet. Run: python -m rfp_scraper scrape")
    for r in rows:
        due = r["due_date"] or "no due date"
        print(f"[{due}] (score {r['score']}) {r['title']}\n    {r['agency']} - {r['url']}\n"
              f"    {', '.join(r['categories'])}")
    return 0


def cmd_serve(args) -> int:
    from .web.app import create_app

    app = create_app(db_path=args.db)
    app.run(host=args.host, port=args.port, debug=False)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="rfp_scraper", description="Find engineering RFPs on Wisconsin public sites.")
    p.add_argument("--db", default=str(config.DB_PATH), help="SQLite file (default: data/rfps.db)")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scrape", help="check all sources now")
    s.add_argument("--source", action="append", help="only sources whose name contains this (repeatable)")
    s.set_defaults(func=cmd_scrape)

    s = sub.add_parser("list", help="print open RFPs")
    s.add_argument("--sort", choices=["due", "score", "newest"], default="due")
    s.set_defaults(func=cmd_list)

    s = sub.add_parser("serve", help="start the dashboard")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=5000)
    s.set_defaults(func=cmd_serve)

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s %(message)s")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
