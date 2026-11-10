"""`/api/productos/agrupados` through the Flask client (products blueprint).

HTTP-level tests for the seleccion-smart feature (T3, D-6): the grouped
payload of §3 served over the same blueprint that owns `/supermercados`,
with the same legacy error fallback shape adapted to the grouped keys.
"""

import logging

from api.repositories import RepositoryUnavailable


EMPTY_FALLBACK = {
    "productos": [],
    "carre": 0,
    "disco": 0,
    "mami": 0,
    "hiper": 0,
    "chang": 0,
}

# Non-database failures must never be reported as a database outage.
_DEFECT_ERROR = "Internal server error"


def get_json(client):
    response = client.get("/api/productos/agrupados")
    assert response.status_code == 200
    return response.get_json()


def test_happy_path_payload_shape(repository, client):
    # -- one EAN pair, one canonical-key pair (brand + presentation) and
    # one product carried by a single chain only.
    repository.documents = [
        {"supermercado": "disco", "name": "Aceite de girasol Natura 900 cc",
         "unidad": "900 cc", "brand": "Natura", "price": 1200,
         "ean": "7790272001005"},
        {"supermercado": "carrefour",
         "name": "Aceite de girasol Natura 900 cc", "unidad": "900 cc",
         "brand": "Natura", "price": 1150.5, "ean": "7790272001005"},
        {"supermercado": "supermami", "name": "Yerba Playadito 1 kg",
         "unidad": "1 kg", "brand": "Playadito", "price": 900},
        {"supermercado": "hiperlibertad", "name": "Playadito Yerba 1 kg",
         "unidad": "1 kg", "brand": "Playadito", "price": 880},
        {"supermercado": "disco", "name": "Cafe Dolca", "price": 1500},
    ]
    payload = get_json(client)

    assert payload["carre"] == 1
    assert payload["disco"] == 2
    assert payload["mami"] == 1
    assert payload["hiper"] == 1

    productos = payload["productos"]
    assert len(productos) == 3

    # -- deterministic ordering: by display name, then stable id
    names = [row["name"] for row in productos]
    assert names == sorted(names)

    for row in productos:
        assert set(row.keys()) == {
            "id", "name", "unidad", "brand", "offers", "match"}
        assert row["id"]
        for offer in row["offers"].values():
            assert set(offer.keys()) == {"name", "price"}

    aceite = next(row for row in productos
                  if row["match"] == "ean")
    assert "Natura" in aceite["name"]
    assert aceite["brand"] == "Natura"
    assert aceite["unidad"] == "900 cc"
    assert aceite["offers"] == {
        "disco": {"name": "Aceite de girasol Natura 900 cc",
                  "price": 1200},
        "carre": {"name": "Aceite de girasol Natura 900 cc",
                  "price": 1150.5},
    }

    yerba = next(row for row in productos if row["match"] == "key")
    assert set(yerba["offers"]) == {"mami", "hiper"}

    cafe = next(row for row in productos if row["match"] == "solo")
    assert cafe["offers"] == {"disco": {"name": "Cafe Dolca",
                                        "price": 1500}}


def test_grouping_joins_two_docs_into_one_row(repository, client):
    repository.documents = [
        {"supermercado": "disco", "name": "Arroz Gallo", "price": 100,
         "ean": "7791234000011"},
        {"supermercado": "carrefour", "name": "Arroz Gallo", "price": 95,
         "ean": "7791234000011"},
    ]
    payload = get_json(client)
    assert payload["disco"] == 1
    assert payload["carre"] == 1
    assert len(payload["productos"]) == 1
    row = payload["productos"][0]
    assert row["match"] == "ean"
    assert set(row["offers"]) == {"disco", "carre"}


def test_repository_unavailable_answers_the_legacy_fallback_and_log(
        repository, client, caplog):
    # RepositoryUnavailable is the translated shape of a driver failure: the
    # legacy 'Database connection error' fallback AND the legacy
    # 'Error reading from MongoDB' signal must both stay intact.
    repository.find_all_error = RepositoryUnavailable("mock outage")
    with caplog.at_level(logging.ERROR):
        response = client.get("/api/productos/agrupados")
    assert response.status_code == 200
    assert response.get_json() == {
        **EMPTY_FALLBACK, "error": "Database connection error"}
    assert "Error reading from MongoDB" in caplog.text


def test_unexpected_failure_is_not_labelled_database_error(
        repository, client, caplog):
    repository.find_all_error = RuntimeError("boom")
    with caplog.at_level(logging.ERROR):
        response = client.get("/api/productos/agrupados")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload == {**EMPTY_FALLBACK, "error": _DEFECT_ERROR}
    assert "Error reading from MongoDB" not in caplog.text


def test_empty_repository_returns_empty_payload_no_error_key(client):
    assert get_json(client) == EMPTY_FALLBACK
    response = client.get("/api/productos/agrupados")
    assert "error" not in response.get_json()
