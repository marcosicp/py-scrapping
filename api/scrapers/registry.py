"""Explicit scraper registry.

No filesystem magic: every scraper class is registered by hand (or with
``@registry.register``), so adding a supermarket is one import plus one
registration line.
"""

from __future__ import annotations

import re
from typing import Iterable

from api.scrapers.base import BaseScraper
from api.scrapers.carrefour import ScraperCarrefour
from api.scrapers.changomas import ScraperChangoMas
from api.scrapers.disco import ScraperDisco
from api.scrapers.errors import UnknownScraper
from api.scrapers.laanonima import ScraperLaAnonima
from api.scrapers.supermami import ScraperSuperMami

SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class ScraperRegistry:
    """Ordered registry of scraper classes keyed by slug."""

    def __init__(self, scrapers: Iterable[type[BaseScraper]] = ()) -> None:
        self._scrapers: dict[str, type[BaseScraper]] = {}
        for scraper in scrapers:
            self.register(scraper)

    # -- registration --------------------------------------------------------

    def register(self, scraper: type[BaseScraper]) -> type[BaseScraper]:
        """Register a scraper class and return it, so this works as a decorator."""
        if not (isinstance(scraper, type) and issubclass(scraper, BaseScraper)):
            raise ValueError(f"{scraper!r} is not a BaseScraper subclass")
        slug = getattr(scraper, "slug", None)
        if not isinstance(slug, str) or not SLUG_PATTERN.fullmatch(slug):
            raise ValueError(f"Invalid scraper slug: {slug!r}")
        label = getattr(scraper, "label", None)
        if not isinstance(label, str) or not label:
            raise ValueError(f"Scraper '{slug}' has an empty label")
        if slug in self._scrapers:
            raise ValueError(f"Scraper slug '{slug}' is already registered")
        self._scrapers[slug] = scraper
        return scraper

    # -- lookup ----------------------------------------------------------------

    def get(self, slug: str) -> type[BaseScraper]:
        """The scraper class registered under ``slug``."""
        try:
            return self._scrapers[slug]
        except KeyError:
            raise UnknownScraper(slug) from None

    def slugs(self) -> list[str]:
        """Registered slugs, in registration order."""
        return list(self._scrapers)

    def classes(self) -> list[type[BaseScraper]]:
        """Registered scraper classes, in registration order."""
        return list(self._scrapers.values())

    # -- protocol conveniences ---------------------------------------------------

    def __iter__(self):
        return iter(self.classes())

    def __len__(self) -> int:
        return len(self._scrapers)

    def __contains__(self, slug: object) -> bool:
        return slug in self._scrapers


def default_registry() -> ScraperRegistry:
    """The registry used by the app: all five supermarket scrapers, ported
    to the scraper contract (T7-T11).

    ``laanonima`` replaced ``hiperlibertad``: that domain now answers 301 to
    laanonima.com.ar and the VTEX API the old module consumed answers 403.
    """
    registry = ScraperRegistry()
    registry.register(ScraperSuperMami)
    registry.register(ScraperLaAnonima)
    registry.register(ScraperDisco)
    registry.register(ScraperCarrefour)
    registry.register(ScraperChangoMas)
    return registry
