"""Tests for the shared HTTP session builder.

The scrapers must keep their historical request fingerprint: the exact
Safari User-Agent the original sessions always sent. Plain ``requests``
would send ``python-requests/x.y`` instead; the pin below is the exact
literal string, character for character.
"""

import requests

from api.scrapers.http import BROWSER_USER_AGENT, build_http_session

EXPECTED_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_12_6) "
    "AppleWebKit/603.3.8 (KHTML, like Gecko) Version/10.1.2 Safari/603.3.8")


def test_user_agent_constant_is_the_pinned_literal():
    assert BROWSER_USER_AGENT == EXPECTED_USER_AGENT


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
