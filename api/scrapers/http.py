"""Shared HTTP session for the scrapers.

The scrapers must keep their historical request fingerprint: the exact
Safari ``User-Agent`` the original sessions always sent; plain ``requests``
would send ``python-requests/x.y`` instead.
"""

from __future__ import annotations

import requests

# The exact Safari User-Agent the scrapers' sessions have always sent; see
# D9 in the feature document.
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_12_6) "
    "AppleWebKit/603.3.8 (KHTML, like Gecko) Version/10.1.2 Safari/603.3.8")


def build_http_session() -> requests.Session:
    """A ``requests.Session`` carrying the legacy browser User-Agent."""
    session = requests.Session()
    session.headers["User-Agent"] = BROWSER_USER_AGENT
    return session
