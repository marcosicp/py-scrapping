"""Composition root: Services stored in app.extensions (T3, D2)."""

import pytest

from api.container import EXTENSION_KEY, Services, get_services, init_services
from api.repositories.products import MongoProductRepository
from api.services.products import ProductService
from app import create_app
from tests.fakes import InMemoryProductRepository


@pytest.fixture
def fake():
    return InMemoryProductRepository()


def test_init_services_stores_services_under_extension_key(app, settings, fake):
    services = init_services(app, settings, fake)
    assert app.extensions[EXTENSION_KEY] is services
    assert isinstance(services, Services)
    assert services.settings is settings
    assert isinstance(services.products, ProductService)


def test_get_services_inside_app_context(app, settings, fake):
    services = init_services(app, settings, fake)
    with app.app_context():
        assert get_services() is services


def test_get_services_without_a_registered_app_raises(app):
    app.extensions.pop(EXTENSION_KEY)
    with app.app_context():
        with pytest.raises(RuntimeError):
            get_services()


def test_create_app_wires_the_injected_repository(settings):
    fake = InMemoryProductRepository()
    fake.documents = [{"supermercado": "disco", "name": "yerba"}]
    app = create_app(settings, repository=fake)
    with app.app_context():
        payload = get_services().products.catalog()
    assert payload["disco"] == 1
    assert payload["todos"] == [{"supermercado": "disco", "name": "yerba"}]


def test_create_app_defaults_to_the_mongo_repository(settings):
    app = create_app(settings)
    services = app.extensions[EXTENSION_KEY]
    repository = services.products._repository
    assert isinstance(repository, MongoProductRepository)
