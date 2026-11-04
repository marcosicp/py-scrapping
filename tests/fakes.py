"""In-memory fakes for tests.

These stand in for the infrastructure the repositories (and, in later tasks,
the services and blueprints) depend on, so tests never touch MongoDB or Flask.

``FakeCollection`` mimics only the pymongo calls the code uses; anything it
does not understand raises so tests fail loudly instead of silently passing.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Optional, Sequence

import bson

from api.scrapers.base import BaseScraper
from api.services.scraping import RunStatus


class Result:
    """Minimal stand-in for pymongo write results."""

    def __init__(self, inserted_ids=None, deleted_count: int = 0):
        self.inserted_ids = inserted_ids if inserted_ids is not None else []
        self.deleted_count = deleted_count


class InsertManyResult(Result):
    pass


class DeleteManyResult(Result):
    pass


class FakeCollection:
    """In-memory copy of the pymongo collection surface the repos use."""

    def __init__(self) -> None:
        self.documents: list[dict[str, Any]] = []
        self.events: list[str] = []
        self.fail_insert: Exception | None = None
        self.fail_find: Exception | None = None

    # -- helpers ---------------------------------------------------------
    @staticmethod
    def _project(document: Mapping[str, Any],
                 projection: Optional[Mapping[str, Any]]) -> dict[str, Any]:
        if projection is None:
            return copy.deepcopy(document)
        if set(projection) != {"_id"}:
            raise NotImplementedError(f"Unsupported projection: {projection!r}")
        if projection["_id"]:
            # {"_id": 1} -> only the id, like MongoDB.
            return {"_id": document["_id"]}
        # {"_id": 0} -> everything but the id.
        return {key: copy.deepcopy(value)
                for key, value in document.items() if key != "_id"}

    def _matches(self, document: Mapping[str, Any],
                 filter_: Optional[Mapping[str, Any]]) -> bool:
        if not filter_:
            return True
        for key, expected in filter_.items():
            if key == "_id" and isinstance(expected, dict):
                if set(expected.keys()) != {"$in"}:
                    raise NotImplementedError(
                        f"Unsupported _id operator: {expected!r}")
                if document.get("_id") not in expected["$in"]:
                    return False
            elif document.get(key) != expected:
                return False
        return True

    # -- pymongo surface -------------------------------------------------
    def find(self, filter=None, projection=None):
        self.events.append("find")
        if self.fail_find is not None:
            raise self.fail_find
        return [self._project(doc, projection)
                for doc in self.documents if self._matches(doc, filter)]

    def insert_many(self, documents: Sequence[Mapping[str, Any]]):
        self.events.append("insert_many")
        if self.fail_insert is not None:
            raise self.fail_insert
        inserted_ids = []
        for doc in documents:
            # pymongo mutates the dicts it is given, attaching the ObjectId.
            doc["_id"] = bson.ObjectId()
            inserted_ids.append(doc["_id"])
            self.documents.append(dict(doc))
        return InsertManyResult(inserted_ids=inserted_ids)

    def delete_many(self, filter):
        self.events.append("delete_many")
        before = len(self.documents)
        self.documents = [doc for doc in self.documents
                          if not self._matches(doc, filter)]
        return DeleteManyResult(deleted_count=before - len(self.documents))


class FakeDatabase:
    """One cached FakeCollection per name, like pymongo's Database."""

    def __init__(self) -> None:
        self._collections: dict[str, FakeCollection] = {}

    def __getitem__(self, name: str) -> FakeCollection:
        if name not in self._collections:
            self._collections[name] = FakeCollection()
        return self._collections[name]


class InMemoryProductRepository:
    """Fake implementing the ProductRepository contract for later tasks."""

    def __init__(self) -> None:
        self.documents: list[dict[str, Any]] = []
        self.calls: list[tuple[str, str | None, str | None, int]] = []
        self.find_all_error: Exception | None = None

    # shared helpers -----------------------------------------------------
    @staticmethod
    def _matches(document: Mapping[str, Any],
                 scope: Mapping[str, Any]) -> bool:
        return all(document.get(key) == value
                   for key, value in scope.items())

    def find_all(self) -> list[dict[str, Any]]:
        if self.find_all_error is not None:
            raise self.find_all_error
        return [{key: copy.deepcopy(value) for key, value in doc.items()
                 if key != "_id"} for doc in self.documents]

    def replace_products(self, supermercado: str,
                         products: Sequence[Mapping[str, Any]], *,
                         categoria: str | None = None,
                         subcategoria: str | None = None) -> int:
        if not products:
            return 0
        scope: dict[str, Any] = {"supermercado": supermercado}
        if categoria is not None:
            scope["categoria"] = categoria
        if subcategoria is not None:
            scope["subcategoria"] = subcategoria
        self.documents = [doc for doc in self.documents
                          if not self._matches(doc, scope)]
        scraped_at = datetime.now(timezone.utc)
        for product in products:
            doc = dict(product)
            doc["supermercado"] = supermercado
            doc["scraped_at"] = scraped_at
            if categoria is not None:
                doc["categoria"] = categoria
            if subcategoria is not None:
                doc["subcategoria"] = subcategoria
            self.documents.append(doc)
        count = len(products)
        self.calls.append((supermercado, categoria, subcategoria, count))
        return count


class RecordingReporter:
    """ProgressReporter fake that records every message and state."""

    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []
        self.states: list[RunStatus] = []

    def message(self, slug: str, text: str) -> None:
        self.messages.append((slug, text))

    def state(self, status: RunStatus) -> None:
        self.states.append(status)


def make_scraper(slug: str, label: str, run: Callable[..., Any],
                 categories: Sequence[str] = ()) -> type:
    """Build a ``BaseScraper`` subclass with ``run`` in the class namespace.

    ``run`` is handed to ``type(...)`` so it becomes a real method: assigning
    it after class creation would leave the abstract ``run`` untouched and
    instantiation would fail.
    """
    class_name = "Scraper" + slug.replace("-", " ").title().replace(" ", "")
    return type(class_name, (BaseScraper,), {
        "slug": slug,
        "label": label,
        "categories": tuple(categories),
        "run": run,
    })
