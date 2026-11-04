"""Contract every registered scraper must satisfy (D3, T7).

Parametrized over ``default_registry()`` so each new port is picked up
automatically: the empty registry passes trivially, and a port that breaks
the contract fails here.

The PRE-CANCELLED guard is the one every future port inherits: with the
stop event already set, a run must not fetch, must not build a browser and
must not save anything.
"""
import re
import threading

import pytest

from api.scrapers.base import ScrapeContext
from api.scrapers.registry import default_registry
from tests.fakes import InMemoryProductRepository

SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

# Resolved at collection time; grows automatically with every new port.
REGISTRY_CLASSES = default_registry().classes()


@pytest.fixture(params=REGISTRY_CLASSES, ids=[c.slug for c in REGISTRY_CLASSES])
def scraper_cls(request):
    return request.param


def test_slug_is_a_valid_url_and_channel_id(scraper_cls):
    assert SLUG_PATTERN.fullmatch(scraper_cls.slug)


def test_label_is_non_empty(scraper_cls):
    assert isinstance(scraper_cls.label, str)
    assert scraper_cls.label


def test_categories_is_a_tuple_of_non_empty_strings(scraper_cls):
    assert isinstance(scraper_cls.categories, tuple)
    for category in scraper_cls.categories:
        assert isinstance(category, str) and category


def test_the_class_instantiates(scraper_cls):
    instance = scraper_cls()
    assert isinstance(instance, scraper_cls)


def test_validate_category_accepts_none(scraper_cls):
    assert scraper_cls.validate_category(None) is None


def test_pre_cancelled_run_is_inert(scraper_cls):
    """A run whose stop event is already set does nothing at all."""
    stop_event = threading.Event()
    stop_event.set()

    http_built = []
    fetched = []
    browsers = []

    def http_factory():
        http_built.append("http")

        class ForbiddenHttp:
            def get(self, url):
                fetched.append(url)
                raise AssertionError(
                    "pre-cancelled run fetched " + url)

        return ForbiddenHttp()

    class ForbiddenBrowser:
        def quit(self):
            pass

    def browser_factory():
        browsers.append("browser")
        return ForbiddenBrowser()

    repository = InMemoryProductRepository()
    messages: list[str] = []
    ctx = ScrapeContext(
        slug=scraper_cls.slug, label=scraper_cls.label, category=None,
        stop_event=stop_event, report=messages.append, repository=repository,
        browser_factory=browser_factory, http_factory=http_factory)

    # Must not raise.
    scraper_cls().run(ctx)

    assert fetched == []
    assert http_built == []
    assert browsers == []
    assert repository.calls == []
    assert repository.documents == []
