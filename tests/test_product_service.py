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
        "chang": 0,
    }


def test_catalog_buckets_laanonima_into_the_hiper_payload_key():
    """La Anónima replaced HiperLibertad: its documents must reach the bucket
    the Angular dashboard already renders (``items!.hiper``), and legacy
    HiperLibertad rows stored in an older database must keep landing there."""
    repository = InMemoryProductRepository()
    repository.documents = [
        {"supermercado": "La Anónima", "name": "azucar"},
        {"supermercado": "hiperlibertad", "name": "yerba"},
    ]
    payload = ProductService(repository).catalog()
    assert payload["hiper"] == 2
    assert [p["name"] for p in payload["todos"]] == ["azucar", "yerba"]


def test_catalog_empty_repository():
    payload = ProductService(InMemoryProductRepository()).catalog()
    assert payload == {
        "todos": [],
        "carre": 0,
        "disco": 0,
        "mami": 0,
        "hiper": 0,
        "chang": 0,
    }


def test_catalog_buckets_changomas_into_the_chang_payload_key():
    """ChangoMás is no longer the open half of K-12: its documents must be
    counted and rendered in ``todos`` under the ``chang`` payload key for
    every stored spelling."""
    repository = InMemoryProductRepository()
    repository.documents = [
        {"supermercado": "ChangoMas", "name": "azucar"},
        {"supermercado": "ChangoMás", "name": "yerba"},
        {"supermercado": "CHANGOMAS", "name": "fideos"},
    ]
    payload = ProductService(repository).catalog()
    assert payload["chang"] == 3
    assert payload["carre"] == 0
    assert payload["disco"] == 0
    assert payload["mami"] == 0
    assert payload["hiper"] == 0
    assert [p["name"] for p in payload["todos"]] == [
        "azucar", "fideos", "yerba"]


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


# -- grouped_catalog + the category dimension (T3) -------------------------


def _categorized_repository():
    """Two categories, one cross-chain row and one single-chain row each."""
    repository = InMemoryProductRepository()
    repository.documents = [
        {"supermercado": "disco", "name": "Aceite Natura 900 cc",
         "unidad": "900 cc", "brand": "Natura", "price": 1200,
         "ean": "7790272001005", "categoria": "almacen"},
        {"supermercado": "carrefour", "name": "Aceite Natura 900 cc",
         "unidad": "900 cc", "brand": "Natura", "price": 1150.5,
         "ean": "7790272001005", "categoria": "almacen"},
        {"supermercado": "supermami", "name": "Yerba Playadito 1 kg",
         "unidad": "1 kg", "brand": "Playadito", "price": 900,
         "categoria": "almacen"},
        {"supermercado": "disco", "name": "Coca 2 L", "unidad": "2 L",
         "brand": "Coca Cola", "price": 800,
         "categoria": "bebidas"},
        {"supermercado": "carrefour", "name": "Coca dos litros",
         "unidad": "2 L", "brand": "Coca Cola", "price": 750,
         "categoria": "bebidas"},
    ]
    return repository


def test_grouped_catalog_adds_sorted_categorias_and_row_categoria():
    payload = ProductService(_categorized_repository()).grouped_catalog()
    assert payload["categorias"] == ["almacen", "bebidas"]
    assert {row["categoria"] for row in payload["productos"]} == {
        "almacen", "bebidas"}


def test_grouped_catalog_without_filter_keeps_whole_catalog_shape():
    payload = ProductService(_categorized_repository()).grouped_catalog()
    assert payload["carre"] == 2
    assert payload["disco"] == 2
    assert payload["mami"] == 1
    # aceite (ean pair), yerba (solo), and two Coca solos — "Coca 2 L" and
    # "Coca dos litros" carry different token sets, so they stay apart
    assert len(payload["productos"]) == 4


def test_grouped_catalog_filters_rows_but_not_the_bucket_counts():
    """C-2: the filter applies to grouped rows, never to documents — a
    cross-chain row keeps all its offers — and the five bucket counts stay
    computed over the whole catalog in every case."""
    payload = ProductService(_categorized_repository()).grouped_catalog(
        "almacen")
    assert payload["carre"] == 2  # whole-catalog count, untouched
    assert payload["disco"] == 2
    assert payload["mami"] == 1
    assert payload["chang"] == 0
    rows = payload["productos"]
    assert all(row["categoria"] == "almacen" for row in rows)
    aceite = next(row for row in rows if row["match"] == "ean")
    assert set(aceite["offers"]) == {"disco", "carre"}


def test_grouped_catalog_unknown_categoria_yields_empty_productos():
    """C-5: an unknown slug is not an error: empty ``productos`` next to the
    full ``categorias``. The service filters only a truthy slug, so an empty
    string behaves like no filter (the blueprint passes the query string
    through untouched)."""
    service = ProductService(_categorized_repository())
    payload = service.grouped_catalog("no-existe")
    assert payload["productos"] == []
    assert payload["categorias"] == ["almacen", "bebidas"]
    assert payload["carre"] == 2
    # empty string behaves like no filter: 4 rows over the whole catalog
    whole = service.grouped_catalog("")
    assert len(whole["productos"]) == 4


def test_grouped_catalog_empty_repository_has_empty_categorias():
    payload = ProductService(InMemoryProductRepository()).grouped_catalog()
    assert payload["categorias"] == []
    assert payload["productos"] == []
