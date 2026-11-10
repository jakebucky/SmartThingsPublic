"""Polite HTTP: identifies itself, respects robots.txt, and rate-limits per host."""
from __future__ import annotations

import os
import time
from urllib import robotparser
from urllib.parse import urlparse

import requests

USER_AGENT = os.environ.get(
    "RFP_USER_AGENT",
    "RFP-Finder/0.1 (public-procurement monitor; python-requests)",
)
DEFAULT_DELAY = float(os.environ.get("RFP_REQUEST_DELAY", "1.5"))
TIMEOUT = 30


class Fetcher:
    def __init__(self, delay: float = DEFAULT_DELAY, session: requests.Session | None = None):
        self.delay = delay
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.8"})
        self._last_hit: dict[str, float] = {}
        self._robots: dict[str, robotparser.RobotFileParser | None] = {}

    def _allowed(self, url: str) -> bool:
        parts = urlparse(url)
        root = f"{parts.scheme}://{parts.netloc}"
        if root not in self._robots:
            rp = robotparser.RobotFileParser()
            try:
                r = self.session.get(root + "/robots.txt", timeout=TIMEOUT)
                if r.status_code == 200:
                    rp.parse(r.text.splitlines())
                    self._robots[root] = rp
                else:
                    self._robots[root] = None  # no robots.txt -> allowed
            except requests.RequestException:
                self._robots[root] = None
        rp = self._robots[root]
        return rp is None or rp.can_fetch(USER_AGENT, url)

    def _wait(self, url: str) -> None:
        host = urlparse(url).netloc
        last = self._last_hit.get(host)
        if last is not None:
            remaining = self.delay - (time.monotonic() - last)
            if remaining > 0:
                time.sleep(remaining)
        self._last_hit[host] = time.monotonic()

    def get(self, url: str, **kwargs) -> requests.Response:
        if not self._allowed(url):
            raise PermissionError(f"robots.txt disallows {url}")
        self._wait(url)
        resp = self.session.get(url, timeout=TIMEOUT, **kwargs)
        resp.raise_for_status()
        return resp
