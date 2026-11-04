"""ProductService.catalog() directly, without the HTTP layer (T3).

The service never swallows repository exceptions: the blueprint owns the
fallback so the legacy ``try/except`` boundary in ``api/routes.py`` is kept,
just moved.
"""

from api.services.products import ProductService
from tests.fakes import InMemoryProductRepository


def test_catalog_happy_path_matches_legacy_payload():
    repository = InMemoryProductRepository()
    repository.documents = [
        {"supermercado": "carrefour", "name": "azucar"},
        {"supermercado": "disco", "name": "yerba"},
        {"supermercado": "supermami", "name": "arroz"},
        {"supermercado": "hiperlibertad", "name": "fideos"},
    ]
    payload = ProductService(repository).catalog()
    assert payload == {
        "todos": [
            {"supermercado": "supermami", "name": "arroz"},
            {"supermercado": "carrefour", "name": "azucar"},
            {"supermercado": "hiperlibertad", "name": "fideos"},
            {"supermercado": "disco", "name": "yerba"},
        ],
        "carre": 1,
        "disco": 1,
        "mami": 1,
        "hiper": 1,
    }


def test_catalog_empty_repository():
    payload = ProductService(InMemoryProductRepository()).catalog()
    assert payload == {
        "todos": [],
        "carre": 0,
        "disco": 0,
        "mami": 0,
        "hiper": 0,
    }


def test_catalog_propagates_repository_exceptions_untouched():
    repository = InMemoryProductRepository()
    error = RuntimeError("mongo is down")
    repository.find_all_error = error
    service = ProductService(repository)
    try:
        service.catalog()
    except RuntimeError as raised:
        assert raised is error
    else:
        raise AssertionError("catalog() swallowed the repository exception")


def test_catalog_propagates_keyerror_from_nameless_document():
    repository = InMemoryProductRepository()
    repository.documents = [{"supermercado": "disco"}]  # no "name"
    try:
        ProductService(repository).catalog()
    except KeyError:
        pass
    else:
        raise AssertionError("catalog() swallowed KeyError from a nameless doc")
