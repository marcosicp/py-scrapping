"""Shared pytest fixtures for the LaListita test suite."""
import contextlib

import pytest

from api.config import Settings
from api.container import EXTENSION_KEY
from api.scrapers.errors import NotRunning, UnknownScraper
from api.scrapers.registry import ScraperRegistry
from app import create_app
from tests.fakes import InMemoryProductRepository, RecordingReporter

JOIN_TIMEOUT = 5.0


@pytest.fixture
def settings():
    # MONGODB_URI points at an unroutable address on purpose: any accidental
    # database access during a test fails fast and can never reach a real
    # database.
    return Settings(
        secret_key="test-secret",
        mongodb_uri="mongodb://127.0.0.1:1/?serverSelectionTimeoutMS=200",
        mongodb_db="lalistita_test",
    )


@pytest.fixture
def repository():
    return InMemoryProductRepository()


@pytest.fixture
def recorder():
    return RecordingReporter()


@pytest.fixture
def app(settings, repository):
    application = create_app(settings, repository=repository)
    application.config["TESTING"] = True
    return application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def scraper_app_factory(settings, repository, recorder):
    """Build apps whose scraper registry and reporter are the test's own.

    The teardown stops any active run and joins every ``scraper-*`` thread,
    so no test can leak a run into the next one.
    """
    apps = []

    def factory(*scrapers):
        application = create_app(
            settings,
            repository=repository,
            scraper_registry=ScraperRegistry(scrapers),
            reporter=recorder,
        )
        application.config["TESTING"] = True
        apps.append(application)
        return application

    yield factory

    for application in apps:
        manager = application.extensions[EXTENSION_KEY].scrapers
        for slug in manager.registry.slugs():
            with contextlib.suppress(NotRunning, UnknownScraper):
                manager.stop(slug)
            manager.wait(slug, timeout=JOIN_TIMEOUT)
