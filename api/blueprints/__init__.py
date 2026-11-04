"""Blueprint registration: HTTP concerns read from the composition root."""

from flask import Flask

from api.blueprints.frontend import frontend
from api.blueprints.legacy import create_legacy_blueprint
from api.blueprints.products import products
from api.blueprints.scrapers import scrapers as scrapers_api
from api.container import EXTENSION_KEY


def register_blueprints(app: Flask) -> None:
    """Attach every blueprint to a fully initialized app.

    The scraper API and the legacy aliases read the ``ScraperManager`` from
    ``app.extensions`` (not ``current_app``: there is no app context at
    registration time), so `init_services` must run first.
    """
    app.register_blueprint(frontend)
    app.register_blueprint(products)
    app.register_blueprint(scrapers_api)
    services = app.extensions[EXTENSION_KEY]
    app.register_blueprint(
        create_legacy_blueprint(services.scrapers.registry.slugs()))
