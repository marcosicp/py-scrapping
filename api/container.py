"""Composition root (D2): one place builds and publishes the services.

``Services`` is stored in ``app.extensions[EXTENSION_KEY]`` so blueprints can
read collaborators from the running application and tests can inject fakes.
"""

from dataclasses import dataclass

from flask import Flask, current_app

from api.config import Settings
from api.repositories.products import ProductRepository
from api.services.products import ProductService

EXTENSION_KEY = "lalistita"


@dataclass(frozen=True)
class Services:
    """The collaborators the blueprints need, built once in ``create_app``."""

    settings: Settings
    products: ProductService


def init_services(app: Flask, settings: Settings,
                  repository: ProductRepository) -> Services:
    """Build the service set and expose it in ``app.extensions``."""
    services = Services(settings=settings,
                        products=ProductService(repository))
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
