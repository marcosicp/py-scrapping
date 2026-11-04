"""Legacy `/scraping-<slug>` aliases, generated from the registry (D7).

DEPRECATED: these routes are thin aliases of ``POST /api/scrapers/<slug>/start``
and ``POST /api/scrapers/<slug>/stop``. They exist only for the legacy /scrape
page and scripts. Unlike the old routes they never block the request and never
run a second copy of the same scraper (a second start returns 409 instead).

They are generated for registered slugs only; as each scraper is ported
(T7-T11) its old hand-written routes must be removed from ``api/routes.py``.
"""

from collections.abc import Iterable

from flask import Blueprint, jsonify, request

from api.container import get_services
from api.scrapers.errors import ScraperError
from api.blueprints.scrapers import error_payload


def _make_start_view(slug: str):
    def start():
        try:
            get_services().scrapers.start(slug, request.args.get("category"))
        except ScraperError as exc:
            payload, status = error_payload(exc)
            return jsonify({"success": False, **payload}), status
        return jsonify({"success": True}), 200
    return start


def _make_stop_view(slug: str):
    def stop():
        try:
            get_services().scrapers.stop(slug)
        except ScraperError as exc:
            payload, status = error_payload(exc)
            return jsonify({"success": False, **payload}), status
        return jsonify({"success": True}), 200
    return stop


def create_legacy_blueprint(slugs: Iterable[str]) -> Blueprint:
    """The registry-generated alias routes (registered slugs only)."""
    blueprint = Blueprint("legacy_scraping", __name__)
    for slug in slugs:
        blueprint.add_url_rule(f"/scraping-{slug}", endpoint=f"start_{slug}",
                               view_func=_make_start_view(slug),
                               methods=["POST"])
        blueprint.add_url_rule(f"/scraping-{slug}-stop", endpoint=f"stop_{slug}",
                               view_func=_make_stop_view(slug),
                               methods=["GET", "POST"])
    return blueprint
