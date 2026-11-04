"""Contract tests for the ProductRepository port.

The same suite runs against three implementations:

- ``memory``     — ``InMemoryProductRepository`` (tests/fakes.py)
- ``mongo_fake`` — ``MongoProductRepository`` on a ``FakeDatabase``
- ``mongo_real`` — ``MongoProductRepository`` on a real local MongoDB,
  opt-in via ``MONGODB_TEST_URI`` (throwaway ``lalistita_test_*`` database).

Contract tests only use the public API (``find_all`` / ``replace_products``).
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import bson
import pytest
from pymongo.errors import ConnectionFailure

from api.repositories import RepositoryUnavailable
from api.repositories.products import COLLECTION_NAME, MongoProductRepository
from tests.fakes import FakeDatabase, InMemoryProductRepository

_MONGO_TEST_PREFIX = "lalistita_test_"


def _drop_throwaway(client, name):
    """Drop a throwaway ``_MONGO_TEST_PREFIX*`` database, safely.

    The guard reads the name back from the database object the client
    resolves (``client[name].name``), not from the constant the fixture
    derived the request from (R1-2): a resolved name without the throwaway
    prefix fails loudly instead of dropping anything.
    """
    resolved = client[name].name
    assert resolved.startswith(_MONGO_TEST_PREFIX), (
        f"Refusing to drop database {resolved!r}: it does not start with "
        f"the {_MONGO_TEST_PREFIX!r} throwaway prefix")
    client.drop_database(resolved)


def _teardown_throwaway(client, name):
    """Tear down a throwaway client: guarded drop first, client closed last
    — on every path, including a refused drop (N6)."""
    try:
        _drop_throwaway(client, name)
    finally:
        client.close()


# ---------------------------------------------------------------------------
# real-Mongo opt-in (single fixture; guards the drop_database call)
# ---------------------------------------------------------------------------

@pytest.fixture
def real_mongo_db():
    """Yield a throwaway ``lalistita_test_*`` database on a real server."""
    uri = os.environ.get("MONGODB_TEST_URI")
    if not uri:
        pytest.skip("MONGODB_TEST_URI not set: real-Mongo tests are opt-in")
    try:
        from pymongo import MongoClient
    except ImportError:
        pytest.skip("pymongo is not installed")

    client = MongoClient(uri, serverSelectionTimeoutMS=2000)
    try:
        client.admin.command("ping")
    except Exception as exc:  # unreachable server
        pytest.skip(f"MongoDB server did not answer at MONGODB_TEST_URI: {exc}")

    name = f"{_MONGO_TEST_PREFIX}{uuid.uuid4().hex}"
    try:
        yield client[name]
    finally:
        # The guard derives from the database actually about to be dropped
        # and fails instead of dropping when the name is not throwaway (R1-2);
        # the client is closed on every teardown path (N6).
        _teardown_throwaway(client, name)



@pytest.fixture(params=["memory", "mongo_fake", "mongo_real"],
                ids=["memory", "mongo_fake", "mongo_real"])
def repo(request):
    if request.param == "memory":
        return InMemoryProductRepository()
    if request.param == "mongo_fake":
        return MongoProductRepository(FakeDatabase())
    return MongoProductRepository(request.getfixturevalue("real_mongo_db"))


SAMPLE = [
    {"name": "Fideos Lata 500g", "unidad": "500g", "brand": "Lata",
     "price": 12.5},
    {"name": "Arroz Tres 1kg", "unidad": "1kg", "brand": "Tres",
     "price": 9.99},
]


class _GuardStubClient:
    """Stand-in for a ``MongoClient`` in teardown-guard tests.

    Normally ``client[name].name`` equals ``name``; entries in
    ``resolved_names`` inject divergence between the requested name and the
    name of the database object about to be dropped, the accident the
    teardown guard must refuse to drop for (R1-2).
    """

    def __init__(self) -> None:
        self.resolved_names: dict[str, Any] = {}
        self.dropped: list[str] = []
        self.closed = False

    def __getitem__(self, name: str) -> Any:
        return self.resolved_names.setdefault(
            name, SimpleNamespace(name=name))

    def drop_database(self, name: str) -> None:
        self.dropped.append(name)

    def close(self) -> None:
        self.closed = True


def test_teardown_closes_the_client_even_when_the_guard_trips():
    """N6: a refused drop still leaves the client closed — the guard failure
    must not leak the Mongo connection."""
    client = _GuardStubClient()
    client["lalistita_test_abc"].name = "lalistitadev"
    with pytest.raises(AssertionError, match="Refusing to drop"):
        _teardown_throwaway(client, "lalistita_test_abc")
    assert client.dropped == []
    assert client.closed is True


def test_teardown_closes_the_client_after_a_successful_drop():
    client = _GuardStubClient()
    database = client["lalistita_test_abc"]  # name == requested: normal case
    _teardown_throwaway(client, "lalistita_test_abc")
    assert client.dropped == [database.name]
    assert client.closed is True


def test_teardown_guard_refuses_a_database_without_the_throwaway_prefix():
    client = _GuardStubClient()
    # The resolved database object says its name is NOT throwaway: the guard
    # must fail loudly instead of dropping anything.
    client["lalistita_test_abc"].name = "lalistitadev"
    with pytest.raises(AssertionError, match="Refusing to drop"):
        _drop_throwaway(client, "lalistita_test_abc")
    assert client.dropped == []


def test_teardown_guard_drops_the_resolved_database_name():
    client = _GuardStubClient()
    database = client["lalistita_test_abc"]  # name == requested: normal case
    _drop_throwaway(client, "lalistita_test_abc")
    assert client.dropped == [database.name]


# ---------------------------------------------------------------------------
# contract cases (public API only)
# ---------------------------------------------------------------------------

def test_new_repository_is_empty(repo):
    assert repo.find_all() == []


def test_replace_stores_documents_with_metadata(repo):
    count = repo.replace_products("Disco", SAMPLE, categoria="almacen")
    assert count == len(SAMPLE)
    stored = repo.find_all()
    assert len(stored) == len(SAMPLE)
    for doc in stored:
        assert doc["supermercado"] == "Disco"
        assert doc["categoria"] == "almacen"
        assert isinstance(doc["scraped_at"], datetime)
        # Aware-UTC on the memory/fake fakes; real pymongo reads back naive
        # datetimes (BSON stores UTC internally, tzinfo is not preserved).
        assert doc["scraped_at"].tzinfo in (None, timezone.utc)
        assert "_id" not in doc
    assert {doc["name"] for doc in stored} == {p["name"] for p in SAMPLE}


def test_replace_touches_only_its_own_slice(repo):
    repo.replace_products("Disco", SAMPLE, categoria="almacen")
    repo.replace_products("Carrefour", [{"name": "Coca", "price": 1.0}],
                          categoria="bebidas")
    repo.replace_products("Disco", [{"name": "Terron", "price": 2.0}],
                          categoria="limpieza")

    stored = {doc["name"]: doc for doc in repo.find_all()}
    assert set(stored) == {"Fideos Lata 500g", "Arroz Tres 1kg", "Coca",
                           "Terron"}
    assert stored["Coca"]["supermercado"] == "Carrefour"
    assert stored["Coca"]["categoria"] == "bebidas"
    assert stored["Terron"]["categoria"] == "limpieza"


def test_subcategoria_scoping(repo):
    repo.replace_products("HiperLibertad", SAMPLE[:1],
                          categoria="almacen", subcategoria="aceites")
    repo.replace_products("HiperLibertad", [{"name": "Azucar", "price": 3.0}],
                          categoria="almacen", subcategoria="harinas")

    stored = {doc["name"]: doc for doc in repo.find_all()}
    assert set(stored) == {"Fideos Lata 500g", "Azucar"}
    assert stored["Fideos Lata 500g"]["subcategoria"] == "aceites"
    assert stored["Azucar"]["subcategoria"] == "harinas"
    for doc in stored.values():
        assert doc["supermercado"] == "HiperLibertad"
        assert doc["categoria"] == "almacen"


def test_no_categoria_replaces_whole_supermarket(repo):
    repo.replace_products("SuperMami", [{"name": "Pan", "price": 1.0}],
                          categoria="almacen")
    repo.replace_products("Carrefour", SAMPLE)  # another supermarket
    repo.replace_products("SuperMami", [{"name": "Leche", "price": 4.0}])

    stored = {doc["name"]: doc for doc in repo.find_all()}
    # "Pan" is gone even though its categoria differs: a replace without a
    # categoria replaces the whole SuperMami slice.
    assert set(stored) == {"Leche", "Fideos Lata 500g", "Arroz Tres 1kg"}
    assert "categoria" not in stored["Leche"]
    assert stored["Leche"]["supermercado"] == "SuperMami"


def test_empty_products_is_noop_returning_zero(repo):
    repo.replace_products("Disco", SAMPLE, categoria="almacen")
    before = repo.find_all()

    assert repo.replace_products("Disco", [], categoria="almacen") == 0
    assert repo.replace_products("Disco", []) == 0
    assert repo.find_all() == before


def test_supermercado_is_forced_on_every_document(repo):
    poisoned = [{"supermercado": "Otro", "name": "x", "price": 1.0}]
    repo.replace_products("Disco", poisoned, categoria="almacen")
    for doc in repo.find_all():
        assert doc["supermercado"] == "Disco"


def test_caller_dicts_are_not_mutated(repo):
    products = [dict(p) for p in SAMPLE]
    repo.replace_products("Disco", products, categoria="almacen")
    for product in products:
        assert "_id" not in product
        assert "scraped_at" not in product
        assert "categoria" not in product
        assert "supermercado" not in product


# ---------------------------------------------------------------------------
# Mongo adapter specifics against FakeDatabase
# ---------------------------------------------------------------------------

def _fake_repo():
    db = FakeDatabase()
    return MongoProductRepository(db), db[COLLECTION_NAME]


def test_mongo_events_order_on_replace_over_existing_slice():
    repo, collection = _fake_repo()
    repo.replace_products("Disco", SAMPLE, categoria="almacen")
    collection.events.clear()
    repo.replace_products("Disco", SAMPLE, categoria="almacen")
    assert collection.events == ["find", "insert_many", "delete_many"]


def test_mongo_no_delete_many_on_first_insert():
    repo, collection = _fake_repo()
    repo.replace_products("Disco", SAMPLE, categoria="almacen")
    assert collection.events == ["find", "insert_many"]


def test_mongo_empty_products_never_touches_collection():
    repo, collection = _fake_repo()
    assert repo.replace_products("Disco", [], categoria="almacen") == 0
    assert collection.events == []


def test_mongo_failed_insert_keeps_previous_documents():
    repo, collection = _fake_repo()
    repo.replace_products("Disco", SAMPLE, categoria="almacen")
    collection.events.clear()
    collection.fail_insert = RuntimeError("boom")
    with pytest.raises(RuntimeError, match="boom"):
        repo.replace_products("Disco", [{"name": "new", "price": 1.0}],
                              categoria="almacen")
    assert "delete_many" not in collection.events
    assert {doc["name"] for doc in repo.find_all()} == \
        {p["name"] for p in SAMPLE}


def test_mongo_read_failure_translates_to_repository_unavailable():
    # A driver failure raised while reading must surface as the port-level
    # RepositoryUnavailable, never as a raw pymongo type (R3-002).
    database = FakeDatabase()
    collection = database[COLLECTION_NAME]
    collection.fail_find = ConnectionFailure("server unreachable")
    with pytest.raises(RepositoryUnavailable) as excinfo:
        MongoProductRepository(database).find_all()
    assert "server unreachable" in str(excinfo.value)


# ---------------------------------------------------------------------------
# real-Mongo-only: bson encode failure keeps the old slice
# ---------------------------------------------------------------------------

def test_real_mongo_invalid_document_keeps_old_slice(real_mongo_db):
    repo = MongoProductRepository(real_mongo_db)
    repo.replace_products("Disco", SAMPLE, categoria="almacen")
    with pytest.raises(bson.errors.InvalidDocument):
        repo.replace_products("Disco", [{"name": "x", "bad": object()}],
                              categoria="almacen")
    assert {doc["name"] for doc in repo.find_all()} == \
        {p["name"] for p in SAMPLE}
