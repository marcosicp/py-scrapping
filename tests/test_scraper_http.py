"""Tests for the shared HTTP session builder.

``requests_html.HTMLSession`` injects a Safari ``User-Agent``; plain
``requests`` would send ``python-requests/x.y``. The builder must reproduce
exactly that header so the scrapers keep their historical request
fingerprint.
"""

import pytest
import requests

from api.scrapers.http import BROWSER_USER_AGENT, build_http_session

LEGACY_REQUESTS_HTML_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_12_6) "
    "AppleWebKit/603.3.8 (KHTML, like Gecko) Version/10.1.2 Safari/603.3.8"
)


def test_constant_matches_legacy_requests_html_user_agent():
    assert BROWSER_USER_AGENT == LEGACY_REQUESTS_HTML_USER_AGENT


def test_build_http_session_returns_requests_session():
    session = build_http_session()
    try:
        assert isinstance(session, requests.Session)
    finally:
        session.close()


def test_build_http_session_sets_browser_user_agent():
    session = build_http_session()
    try:
        assert session.headers["User-Agent"] == BROWSER_USER_AGENT
    finally:
        session.close()


def test_matches_requests_html_header_characterization():
    requests_html = pytest.importorskip("requests_html")
    legacy_session = requests_html.HTMLSession()
    assert legacy_session.headers["User-Agent"] == BROWSER_USER_AGENT
