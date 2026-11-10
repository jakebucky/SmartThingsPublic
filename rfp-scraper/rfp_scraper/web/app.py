"""Dashboard for browsing, filtering and triaging found RFPs."""
from __future__ import annotations

import csv
import io
import logging
import threading
from datetime import date, datetime
from pathlib import Path

from flask import Flask, Response, flash, g, redirect, render_template, request, url_for

from .. import config, db, runner

log = logging.getLogger("rfp_scraper")


class ScrapeJob:
    """Runs one scrape at a time in a background thread."""

    def __init__(self):
        self.lock = threading.Lock()
        self.running = False
        self.last_message = ""

    def start(self, db_path: str) -> bool:
        with self.lock:
            if self.running:
                return False
            self.running = True
        threading.Thread(target=self._run, args=(db_path,), daemon=True).start()
        return True

    def _run(self, db_path: str) -> None:
        try:
            conn = db.connect(db_path)
            s = runner.run(conn, config.load_sources(), config.load_keywords())
            self.last_message = (
                f"Finished {datetime.now():%b %d %I:%M %p}: {s.sources} sources, "
                f"{s.matched} relevant RFPs, {s.new} new"
                + (f", {len(s.errors)} sources had errors" if s.errors else "")
            )
            conn.close()
        except Exception as exc:  # surface it in the UI rather than dying silently
            log.exception("scrape failed")
            self.last_message = f"Scrape failed: {exc}"
        finally:
            with self.lock:
                self.running = False


def create_app(db_path: str | Path | None = None) -> Flask:
    app = Flask(__name__)
    app.secret_key = "rfp-finder-local"  # only used for flash messages
    app.config["DB_PATH"] = str(db_path or config.DB_PATH)
    job = ScrapeJob()

    def get_db():
        if "db" not in g:
            g.db = db.connect(app.config["DB_PATH"])
        return g.db

    @app.teardown_appcontext
    def close_db(_exc):
        conn = g.pop("db", None)
        if conn is not None:
            conn.close()

    @app.template_filter("pretty_date")
    def pretty_date(value):
        if not value:
            return ""
        try:
            return date.fromisoformat(value[:10]).strftime("%b %d, %Y")
        except ValueError:
            return value

    @app.template_filter("days_left")
    def days_left(value):
        if not value:
            return None
        try:
            return (date.fromisoformat(value[:10]) - date.today()).days
        except ValueError:
            return None

    def filters_from_request():
        return dict(
            q=request.args.get("q", "").strip(),
            category=request.args.get("category", ""),
            source=request.args.get("source", ""),
            status=request.args.get("status", "active"),
            include_expired=request.args.get("expired") == "1",
            sort=request.args.get("sort", "due"),
        )

    @app.get("/")
    def index():
        conn = get_db()
        f = filters_from_request()
        rows = db.query_rfps(conn, **f)
        keywords = config.load_keywords()
        sources = [s["name"] for s in config.load_sources()]
        last_started = db.last_run_started(conn)
        return render_template(
            "index.html",
            rows=rows,
            f=f,
            categories=list((keywords.get("categories") or {}).keys()),
            sources=sources,
            statuses=db.STATUSES,
            last_started=last_started,
            job=job,
        )

    @app.get("/sources")
    def sources_page():
        conn = get_db()
        runs = {r["source"]: r for r in db.latest_runs(conn)}
        return render_template("sources.html", sources=config.load_sources(), runs=runs, job=job)

    @app.post("/scrape")
    def scrape():
        if job.start(app.config["DB_PATH"]):
            flash("Scrape started. It can take a few minutes; refresh to see results.")
        else:
            flash("A scrape is already running.")
        return redirect(request.referrer or url_for("index"))

    @app.post("/rfp/<uid>/status")
    def update_status(uid):
        status = request.form.get("status", "new")
        notes = request.form.get("notes")
        try:
            db.set_status(get_db(), uid, status, notes)
        except ValueError as exc:
            flash(str(exc))
        return redirect(request.referrer or url_for("index"))

    @app.get("/export.csv")
    def export_csv():
        rows = db.query_rfps(get_db(), **filters_from_request())
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["Due date", "Title", "Agency", "Solicitation #", "Categories", "Keywords",
                    "Score", "Status", "Posted", "First seen", "Link", "Notes"])
        for r in rows:
            w.writerow([r["due_date"] or "", r["title"], r["agency"], r["solicitation_id"] or "",
                        "; ".join(r["categories"]), "; ".join(r["keywords"]), r["score"], r["status"],
                        r["posted_date"] or "", r["first_seen"][:10], r["url"], r["notes"] or ""])
        return Response(buf.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": f"attachment; filename=rfps-{date.today()}.csv"})

    return app
