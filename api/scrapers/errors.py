"""Scraper-control errors.

These are raised by the scraper framework and translated to HTTP status
codes by the API layer (T5). No Flask or Mongo dependency: the CLI runner
uses the very same exceptions.
"""


class ScraperError(Exception):
    """Base of every scraper-control error."""


class UnknownScraper(ScraperError):
    """Requested scraper slug is not registered."""

    def __init__(self, slug: str) -> None:
        self.slug = slug
        super().__init__(f"Unknown scraper '{slug}'")


class InvalidCategory(ScraperError):
    """Requested category is not accepted by the scraper."""

    def __init__(self, slug: str, category: str,
                 allowed: tuple[str, ...]) -> None:
        self.slug = slug
        self.category = category
        self.allowed = allowed
        super().__init__(
            f"Invalid category '{category}' for scraper '{slug}'; "
            f"allowed: {', '.join(allowed)}")


class AlreadyRunning(ScraperError):
    """A run of this scraper is already active (HTTP 409 at the API layer)."""

    def __init__(self, slug: str) -> None:
        self.slug = slug
        super().__init__(f"A run of scraper '{slug}' is already active")


class NotRunning(ScraperError):
    """Stop/wait was requested for a scraper that is not running."""

    def __init__(self, slug: str) -> None:
        self.slug = slug
        super().__init__(f"Scraper '{slug}' is not running")
