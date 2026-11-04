"""Composition root (D2): one place builds and publishes the services.

``Services`` is stored in ``app.extensions[EXTENSION_KEY]`` so blueprints can
read collaborators from the running application and tests can inject fakes.
"""

from dataclasses import dataclass

from flask import Flask, current_app

from api.config import Settings
from api.repositories.products import ProductRepository
from api.scrapers.browser import build_chrome
from api.scrapers.registry import ScraperRegistry, default_registry
from api.services.products import ProductService
from api.services.scraping import ScraperManager

EXTENSION_KEY = "lalistita"


@dataclass(frozen=True)
class Services:
    """The collaborators the blueprints need, built once in ``create_app``."""

    settings: Settings
    products: ProductService
    scrapers: ScraperManager


def init_services(app: Flask, settings: Settings,
                  repository: ProductRepository, *,
                  scraper_registry: ScraperRegistry | None = None,
                  reporter=None,
                  browser_factory=None) -> Services:
    """Build the service set and expose it in ``app.extensions``.

    ``scraper_registry`` falls back to ``default_registry()``, which holds
    the ported scrapers (``api/scrapers/registry.py::default_registry``;
    currently SuperMami) and grows as T8-T11 port the rest;
    ``reporter`` is the run progress sink;
    ``browser_factory`` builds the Chrome driver behind ``ctx.browser()``,
    defaulting to ``build_chrome(settings)`` (D8). Importing ``build_chrome``
    here is safe because it brings Selenium in lazily.
    """
    services = Services(settings=settings,
                        products=ProductService(repository),
                        scrapers=ScraperManager(
                            scraper_registry if scraper_registry is not None
                            else default_registry(),
                            repository,
                            reporter=reporter,
                            browser_factory=(
                                browser_factory if browser_factory is not None
                                else lambda: build_chrome(settings))))
    app.extensions[EXTENSION_KEY] = services
    return services


def get_services() -> Services:
    """Services of the application currently answering the request."""
    try:
        return current_app.extensions[EXTENSION_KEY]
    except KeyError as exc:
        raise RuntimeError(
            "No services registered in app.extensions; call init_services(app, ...)"
            " first") from exc
