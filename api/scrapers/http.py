"""Shared HTTP session for the scrapers.

``requests_html.HTMLSession`` injects a Safari ``User-Agent`` into every
request; plain ``requests`` would send ``python-requests/x.y`` instead.
The scrapers keep their historical request fingerprint by using the exact
same header, but without depending on ``requests-html``.
"""

from __future__ import annotations

import requests

# User-Agent that requests_html.HTMLSession used to inject; see D9 in the
# feature document.
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_12_6) "
    "AppleWebKit/603.3.8 (KHTML, like Gecko) Version/10.1.2 Safari/603.3.8")


def build_http_session() -> requests.Session:
    """A ``requests.Session`` carrying the legacy browser User-Agent."""
    session = requests.Session()
    session.headers["User-Agent"] = BROWSER_USER_AGENT
    return session
