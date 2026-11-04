"""Blueprint registration: HTTP concerns read from the composition root."""

from flask import Flask

from api.blueprints.frontend import frontend
from api.blueprints.products import products


def register_blueprints(app: Flask) -> None:
    """Attach the non-scraper blueprints the legacy blueprint shed in T3."""
    app.register_blueprint(frontend)
    app.register_blueprint(products)
