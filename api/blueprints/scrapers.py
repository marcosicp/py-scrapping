"""Scraper-control HTTP API: `/api/scrapers` (design D4).

The views stay thin: they read the `ScraperManager` from the composition
root, translate the scraper-control errors to HTTP status codes and hand
back `RunStatus` snapshots. Any non-scraper exception is deliberately not
swallowed.
"""

from flask import Blueprint, jsonify, request

from api.container import get_services
from api.scrapers.errors import (AlreadyRunning, InvalidCategory, NotRunning,
                                 ScraperError, UnknownScraper)
from api.services.scraping import RunStatus, ScraperManager

scrapers = Blueprint("scrapers", __name__, url_prefix="/api/scrapers")

# Exact error type -> (code, HTTP status). UnknownScraper's subclass
# relationships do not matter: the members of ScraperError are siblings.
_CODES = {
    UnknownScraper: ("unknown_scraper", 404),
    InvalidCategory: ("invalid_category", 400),
    AlreadyRunning: ("already_running", 409),
    NotRunning: ("not_running", 409),
}


def error_payload(exc: Exception) -> tuple[dict, int]:
    """Translate a scraper-control error into an HTTP body and status.

    An unexpected ``ScraperError`` subclass is not a recognized failure, so
    it is re-raised rather than swallowed.
    """
    try:
        code, status = _CODES[type(exc)]
    except KeyError:
        raise exc
    payload = {"error": str(exc), "code": code}
    if isinstance(exc, InvalidCategory):
        payload["allowed"] = list(exc.allowed)
    return payload, status


def describe(manager: ScraperManager, status: RunStatus) -> dict:
    """One status snapshot plus the scraper's accepted categories."""
    return {**status.to_dict(),
            "categories": list(manager.registry.get(status.slug).categories)}


def _manager() -> ScraperManager:
    return get_services().scrapers


@scrapers.get("")
def list_scrapers():
    manager = _manager()
    return jsonify(
        {"scrapers": [describe(manager, status) for status in manager.list()]})


@scrapers.get("/<slug>")
def scraper_status(slug):
    manager = _manager()
    return jsonify(describe(manager, manager.status(slug)))


@scrapers.post("/<slug>/start")
def scraper_start(slug):
    manager = _manager()
    # Query string first, then a JSON body, otherwise no category.
    category = request.args.get("category")
    if category is None:
        body = request.get_json(silent=True)
        if isinstance(body, dict):
            category = body.get("category")
    status = manager.start(slug, category)
    return jsonify(describe(manager, status)), 202


@scrapers.post("/<slug>/stop")
def scraper_stop(slug):
    manager = _manager()
    status = manager.stop(slug)
    return jsonify(describe(manager, status)), 202


@scrapers.errorhandler(ScraperError)
def _handle_scraper_errors(exc):
    # error_payload re-raises unknown ScraperError subclasses, so anything
    # else (including every non-scraper exception) still propagates.
    payload, status = error_payload(exc)
    return jsonify(payload), status
