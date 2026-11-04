"""Scraper contract: ``BaseScraper`` and the ``ScrapeContext`` it runs on.

A scraper is a pure collector: it reports progress, sleeps cooperatively,
saves through the repository and asks the context for a browser or an HTTP
session. It never imports Flask, Mongo or SocketIO, so it is drivable from
the run manager, the CLI or a test alike.
"""

from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod
from contextlib import contextmanager
from typing import Any, Callable, ClassVar, Iterable

from api.repositories.products import ProductRepository
from api.scrapers.errors import InvalidCategory
from api.scrapers.http import build_http_session

logger = logging.getLogger(__name__)

ReportCallback = Callable[[str], None]


class ScrapeContext:
    """Everything a scraper needs for one run, handed to ``run(ctx)``."""

    def __init__(self, *, slug: str, label: str, category: str | None,
                 stop_event: threading.Event, report: ReportCallback,
                 repository: ProductRepository,
                 browser_factory: Callable[[], Any] | None = None,
                 http_factory: Callable[[], Any] = build_http_session
                 ) -> None:
        self._slug = slug
        self._label = label
        self.category = category
        self._stop_event = stop_event
        self._report = report
        self._repository = repository
        self._browser_factory = browser_factory
        self._http_factory = http_factory
        self._http: Any | None = None
        self.saved = 0

    # -- progress ---------------------------------------------------------

    def report(self, message: str) -> None:
        """Forward a progress message to the reporter."""
        self._report(message)

    # -- cooperative stop ---------------------------------------------------

    def should_stop(self) -> bool:
        """True once a stop was requested for this run."""
        return self._stop_event.is_set()

    def sleep(self, seconds: float) -> bool:
        """Sleep ``seconds`` unless a stop is requested first.

        Returns True if the stop was set (the call returned immediately
        or early), False when the full sleep elapsed.
        """
        return self._stop_event.wait(seconds)

    # -- persistence --------------------------------------------------------

    def save(self, products: Iterable[Any], *, categoria: str | None = None,
             subcategoria: str | None = None) -> int:
        """Replace the ``supermercado`` slice with ``products``.

        Mirrors the legacy ``save_to_mongodb`` behaviour: a failed save is
        reported and the scrape continues (returns 0, never raises).
        """
        products = list(products)
        if not products:
            return 0

        scope = subcategoria if subcategoria is not None else (
            categoria if categoria is not None else self._label)
        try:
            count = self._repository.replace_products(
                self._label, products, categoria=categoria,
                subcategoria=subcategoria)
        except Exception:
            logger.exception(
                "Failed to save %s products for '%s'",
                len(products), scope)
            self.report(f"Error al guardar {scope} en base de datos")
            return 0

        self.saved += count
        self.report(f"Guardados {count} productos de {scope} en base de datos")
        return count

    # -- infrastructure seams -------------------------------------------------

    @property
    def http(self) -> Any:
        """The shared HTTP session for this run, built lazily once."""
        if self._http is None:
            self._http = self._http_factory()
        return self._http

    @contextmanager
    def browser(self):
        """Yield the scraper's browser driver, quitting it afterwards."""
        if self._browser_factory is None:
            raise RuntimeError("no browser factory configured")
        driver = self._browser_factory()
        try:
            yield driver
        finally:
            try:
                driver.quit()
            except Exception:
                logger.exception("Failed to quit the browser of '%s'",
                                 self._slug)

    def close(self) -> None:
        """Release the shared HTTP session, if one was built. Never raises."""
        session, self._http = self._http, None
        if session is None:
            return
        try:
            session.close()
        except Exception:
            logger.exception("Failed to close the HTTP session of '%s'",
                             self._slug)


class BaseScraper(ABC):
    """Contract every supermarket scraper implements.

    ``slug`` is the URL/channel id (e.g. ``"disco"``), ``label`` the value
    stored under ``supermercado`` (e.g. ``"Disco"``) and ``categories`` the
    accepted ``category`` values; an empty tuple means the category is not
    supported and is ignored.
    """

    slug: ClassVar[str]
    label: ClassVar[str]
    categories: ClassVar[tuple[str, ...]] = ()

    @abstractmethod
    def run(self, ctx: ScrapeContext) -> None:
        """Run one scrape until completion or a stop request."""
        ...

    @classmethod
    def validate_category(cls, category: str | None) -> str | None:
        """Validate ``category``; None/empty means "no category filter".

        A scraper with ``categories == ()`` ignores any value.
        """
        if not category:
            return None
        if not cls.categories:
            return None
        if category in cls.categories:
            return category
        raise InvalidCategory(cls.slug, category, cls.categories)
