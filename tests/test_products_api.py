"""`/supermercados` through the Flask client (products blueprint) — T3.

These tests fix the public payload contract (D7): the Angular dashboard
consumes it, so the blueprint keeps answering exactly like the legacy view in
``api/routes.py``, now with ``ProductService`` behind the repository port.
"""

import logging

from api.repositories import RepositoryUnavailable


EMPTY_FALLBACK = {
    "todos": [],
    "carre": 0,
    "disco": 0,
    "mami": 0,
    "hiper": 0,
    "chang": 0,
}

# Non-database failures must never be reported as a database outage.
_DEFECT_ERROR = "Internal server error"


def get_json(client):
    response = client.get("/supermercados")
    assert response.status_code == 200
    return response.get_json()


def test_empty_repository_returns_empty_payload_no_error_key(client):
    assert get_json(client) == EMPTY_FALLBACK
    response = client.get("/supermercados")
    assert "error" not in response.get_json()


def test_one_product_per_supermarket_counts_and_sorted_todos(repository, client):
    repository.documents = [
        {"supermercado": "disco", "name": "B"},
        {"supermercado": "carrefour", "name": "D"},
        {"supermercado": "hiperlibertad", "name": "A"},
        {"supermercado": "supermami", "name": "C"},
    ]
    payload = get_json(client)
    assert payload["disco"] == 1
    assert payload["carre"] == 1
    assert payload["mami"] == 1
    assert payload["hiper"] == 1
    assert [p["name"] for p in payload["todos"]] == ["A", "B", "C", "D"]


def test_grouping_is_case_insensitive_and_buckets_every_chain(
        repository, client):
    repository.documents = [
        {"supermercado": "DISCO", "name": "a"},
        {"supermercado": "Carrefour", "name": "b"},
        {"supermercado": "Hiperlibertad", "name": "c"},
        {"supermercado": "hiper", "name": "d"},
        {"supermercado": "SuperMami", "name": "e"},
        {"supermercado": "mami", "name": "f"},
        {"supermercado": "ChangoMas", "name": "g"},
        {"name": "h"},  # no supermercado key at all
    ]
    payload = get_json(client)
    assert payload["disco"] == 1
    assert payload["carre"] == 1
    assert payload["hiper"] == 2
    assert payload["mami"] == 2
    assert payload["chang"] == 1  # ChangoMas is now a visible chain
    assert [p["name"] for p in payload["todos"]] == [
        "a", "b", "c", "d", "e", "f", "g"]


def test_dedupe_by_name_inside_supermarket_keeps_first(repository, client):
    repository.documents = [
        {"supermercado": "disco", "name": "Yerba", "price": 1},
        {"supermercado": "disco", "name": "Yerba", "price": 2},
        {"supermercado": "carrefour", "name": "Yerba", "price": 3},
    ]
    payload = get_json(client)
    # disco deduped to one, carrefour keeps its own copy.
    assert payload["disco"] == 1
    assert payload["carre"] == 1
    yerbas = [p for p in payload["todos"] if p["name"] == "Yerba"]
    assert len(yerbas) == 2
    assert [p["price"] for p in yerbas] == [3, 1]  # carrefour first, disco after


def test_counts_are_post_dedupe(repository, client):
    repository.documents = [
        {"supermercado": "mami", "name": "X"},
        {"supermercado": "mami", "name": "X"},
    ]
    payload = get_json(client)
    assert payload["mami"] == 1
    assert len(payload["todos"]) == 1


def test_stable_tie_break_across_supermarkets(repository, client):
    name = "same-name"
    repository.documents = [
        {"supermercado": "disco", "name": name, "tag": "disco"},
        {"supermercado": "carrefour", "name": name, "tag": "carrefour"},
        {"supermercado": "hiperlibertad", "name": name, "tag": "hiper"},
        {"supermercado": "supermami", "name": name, "tag": "mami"},
    ]
    payload = get_json(client)
    tags = [p["tag"] for p in payload["todos"]]
    # legacy concatenation order: supermami + carrefour + hiperlibertad + disco
    assert tags == ["mami", "carrefour", "hiper", "disco"]


def test_repository_unavailable_answers_the_legacy_fallback_and_log(
        repository, client, caplog):
    # RepositoryUnavailable is the translated shape of a driver failure: the
    # legacy 'Database connection error' fallback AND the legacy
    # 'Error reading from MongoDB' signal must both stay intact.
    repository.find_all_error = RepositoryUnavailable("mock outage")
    with caplog.at_level(logging.ERROR):
        response = client.get("/supermercados")
    assert response.status_code == 200
    assert response.get_json() == {
        **EMPTY_FALLBACK, "error": "Database connection error"}
    assert "Error reading from MongoDB" in caplog.text


def test_product_without_name_is_not_labelled_a_database_error(
        repository, client, caplog):
    # A missing 'name' key is a data defect, not a database outage: it must
    # not answer 'Database connection error' nor log a MongoDB failure.
    repository.documents = [
        {"supermercado": "disco", "price": 5},  # no "name"
    ]
    with caplog.at_level(logging.ERROR):
        response = client.get("/supermercados")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["todos"] == []
    assert payload == {**EMPTY_FALLBACK, "error": _DEFECT_ERROR}
    assert "Error reading from MongoDB" not in caplog.text


def test_unexpected_repository_failure_is_also_not_labelled_database_error(
        repository, client, caplog):
    repository.find_all_error = RuntimeError("boom")
    with caplog.at_level(logging.ERROR):
        response = client.get("/supermercados")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["todos"] == []
    assert payload == {**EMPTY_FALLBACK, "error": _DEFECT_ERROR}
    assert "Error reading from MongoDB" not in caplog.text


def test_successful_payload_has_exactly_the_legacy_keys(repository, client):
    repository.documents = [{"supermercado": "disco", "name": "A"}]
    assert set(get_json(client).keys()) == {"todos", "carre", "disco",
                                            "mami", "hiper", "chang"}
