"""Product persistence port and its MongoDB adapter.

The port preserves the stored document shape of the legacy scrapers
(``save_to_mongodb`` in ``api/scrapers/*.py``): ``supermercado``, ``name``,
``unidad``, ``price``, plus ``categoria``/``subcategoria`` when the scrape
provides them and a UTC ``scraped_at`` stamp added at save time.
``/supermercados`` reads the same documents with ``find({}, {"_id": 0})``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any, Protocol

from pymongo.errors import PyMongoError

from api.repositories import RepositoryUnavailable

COLLECTION_NAME = "productos"


class ProductRepository(Protocol):
    """Persistence port for product documents."""

    def find_all(self) -> list[dict[str, Any]]:
        ...

    def replace_products(self, supermercado: str,
                         products: Sequence[Mapping[str, Any]], *,
                         categoria: str | None = None,
                         subcategoria: str | None = None) -> int:
        ...


class MongoProductRepository:
    """MongoDB adapter backed by ``database`` and the ``productos`` collection."""

    def __init__(self, database) -> None:
        self._collection = database[COLLECTION_NAME]

    def find_all(self) -> list[dict[str, Any]]:
        """Every stored document with the ``_id`` field stripped.

        Driver-level read failures translate to :class:`RepositoryUnavailable`
        (R3-002): the callers must be able to tell a database outage apart
        from any other defect without importing pymongo.
        """
        try:
            return list(self._collection.find({}, {"_id": 0}))
        except PyMongoError as exc:
            raise RepositoryUnavailable(str(exc)) from exc

    def replace_products(self, supermercado: str,
                         products: Sequence[Mapping[str, Any]], *,
                         categoria: str | None = None,
                         subcategoria: str | None = None) -> int:
        """Replace the ``supermercado`` slice with ``products`` (K-8).

        Semantics, in this exact order:

        1. An empty ``products`` is a no-op returning 0: nothing is found,
           deleted or inserted. A broken scrape must never wipe a slice.
        2. The ids currently in the slice are read, then the new documents
           are inserted *before* deleting the old ones, so a failed insert
           leaves the previous data intact (legacy code deleted first).
        3. If the insert fails after some batches (a chunked driver write) were
           already written, the slice can end up
           holding old + partial new documents. ``/supermercados`` already
           deduplicates by product name, and the next successful replace
           deletes every id found in the slice at that moment, so the data
           converges then.

        Returns the number of stored documents.
        """
        # 1. No-op guard before touching the collection at all.
        if not products:
            return 0

        # 2. Scope of the slice being replaced.
        scope: dict[str, Any] = {"supermercado": supermercado}
        if categoria is not None:
            scope["categoria"] = categoria
        if subcategoria is not None:
            scope["subcategoria"] = subcategoria

        # 3. Build documents without mutating the caller's mappings (pymongo
        #    attaches ``_id`` to the inserted dicts).
        scraped_at = datetime.now(timezone.utc)
        documents = []
        for product in products:
            doc = dict(product)
            doc["supermercado"] = supermercado
            doc["scraped_at"] = scraped_at
            if categoria is not None:
                doc["categoria"] = categoria
            if subcategoria is not None:
                doc["subcategoria"] = subcategoria
            documents.append(doc)

        # 4. Read the ids currently inside the slice.
        previous_ids = [doc["_id"] for doc in self._collection.find(
            scope, {"_id": 1})]

        # 5. Insert first; if this raises, delete NOTHING (K-8).
        self._collection.insert_many(documents)

        # 6. Prune exactly the previously observed ids.
        if previous_ids:
            self._collection.delete_many({"_id": {"$in": previous_ids}})

        # 7. Outcome.
        return len(documents)
