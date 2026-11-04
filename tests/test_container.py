"""Composition root: Services stored in app.extensions (T3, D2)."""
import threading

import pytest

from api.container import EXTENSION_KEY, Services, get_services, init_services
from api.repositories.products import MongoProductRepository
from api.scrapers.registry import ScraperRegistry
from api.services.products import ProductService
from api.services.scraping import RunState, ScraperManager
from app import create_app
from tests.fakes import InMemoryProductRepository, RecordingReporter, \
    make_scraper

TIMEOUT = 5.0


@pytest.fixture
def fake():
    return InMemoryProductRepository()


class FakeDriver:
    """Driver stand-in exposing only ``quit()``; never a real Chrome."""

    def __init__(self):
        self.quit_called = False

    def quit(self):
        self.quit_called = True


def browser_scraper(slug, drivers):
    """Fake scraper that borrows the driver through ``ctx.browser()``."""

    def run(self, ctx):
        with ctx.browser() as driver:
            drivers.append(driver)

    return make_scraper(slug, slug.title(), run)


def test_init_services_stores_services_under_extension_key(app, settings, fake):
    services = init_services(app, settings, fake)
    assert app.extensions[EXTENSION_KEY] is services
    assert isinstance(services, Services)
    assert services.settings is settings
    assert isinstance(services.products, ProductService)


def test_get_services_inside_app_context(app, settings, fake):
    services = init_services(app, settings, fake)
    with app.app_context():
        assert get_services() is services


def test_get_services_without_a_registered_app_raises(app):
    app.extensions.pop(EXTENSION_KEY)
    with app.app_context():
        with pytest.raises(RuntimeError):
            get_services()


def test_create_app_wires_the_injected_repository(settings):
    fake = InMemoryProductRepository()
    fake.documents = [{"supermercado": "disco", "name": "yerba"}]
    app = create_app(settings, repository=fake)
    with app.app_context():
        payload = get_services().products.catalog()
    assert payload["disco"] == 1
    assert payload["todos"] == [{"supermercado": "disco", "name": "yerba"}]


def test_create_app_defaults_to_the_mongo_repository(settings):
    app = create_app(settings)
    services = app.extensions[EXTENSION_KEY]
    repository = services.products._repository
    assert isinstance(repository, MongoProductRepository)


def test_services_include_the_scraper_manager(app):
    services = app.extensions[EXTENSION_KEY]
    assert isinstance(services.scrapers, ScraperManager)


def test_create_app_wires_registry_and_reporter_into_the_manager(
        settings, repository):
    recorder = RecordingReporter()
    entered = threading.Event()
    release = threading.Event()

    def run(self, ctx):
        entered.set()
        while not (release.is_set() or ctx.should_stop()):
            ctx.sleep(0.01)

    registry = ScraperRegistry([make_scraper("wired", "Wired", run)])
    app = create_app(settings, repository=repository,
                     scraper_registry=registry, reporter=recorder)
    with app.app_context():
        manager = get_services().scrapers
        assert manager.registry is registry
        assert manager.start("wired").state is RunState.RUNNING
        assert entered.wait(TIMEOUT)
        release.set()
        assert manager.wait("wired", timeout=TIMEOUT).state \
            is RunState.SUCCEEDED

    states = [status.to_dict()["state"] for status in recorder.states]
    assert "running" in states
    assert "succeeded" in states


def test_default_browser_factory_builds_through_build_chrome_with_the_app_settings(
        settings, repository, recorder, scraper_app_factory, monkeypatch):
    built = []

    def recorder_factory(service_settings):
        built.append(service_settings)
        return FakeDriver()

    monkeypatch.setattr("api.container.build_chrome", recorder_factory)
    app = scraper_app_factory(browser_scraper("factory", []))
    manager = app.extensions[EXTENSION_KEY].scrapers
    manager.start("factory")
    assert manager.wait("factory", timeout=TIMEOUT).state is RunState.SUCCEEDED

    assert built == [services_of(app).settings]


def test_browser_borrowed_by_a_run_gets_quit_afterwards(
        settings, repository, recorder, scraper_app_factory, monkeypatch):
    monkeypatch.setattr("api.container.build_chrome", lambda _settings: FakeDriver())
    drivers = []
    app = scraper_app_factory(browser_scraper("quit", drivers))
    manager = app.extensions[EXTENSION_KEY].scrapers
    manager.start("quit")
    assert manager.wait("quit", timeout=TIMEOUT).state is RunState.SUCCEEDED

    assert len(drivers) == 1
    assert drivers[0].quit_called is True


def test_explicit_browser_factory_override_wins(settings, fake):
    handled = []

    def factory():
        driver = FakeDriver()
        handled.append(driver)
        return driver

    app = create_app(settings, repository=fake)
    drivers = []
    registry = ScraperRegistry([browser_scraper("override", drivers)])
    services = init_services(app, settings, fake, scraper_registry=registry,
                             browser_factory=factory)
    manager = services.scrapers
    manager.start("override")
    assert manager.wait("override", timeout=TIMEOUT).state is RunState.SUCCEEDED

    assert handled == drivers == [handled[0]]
    assert drivers[0].quit_called is True


def services_of(application):
    return application.extensions[EXTENSION_KEY]


def test_default_app_lists_the_registered_scrapers(client):
    # The default registry grows one entry per port (T7, T8, ... T11), so
    # this test is registry-driven instead of pinning a count or a name.
    from api.scrapers.registry import default_registry
    slugs = default_registry().slugs()

    response = client.get("/api/scrapers")
    assert response.status_code == 200
    entries = response.get_json()["scrapers"]
    # Exactly one entry per registered slug, in registration order.
    assert [entry["slug"] for entry in entries] == slugs
    for entry in entries:
        assert entry["state"] == "idle"
        assert entry["label"]
        assert isinstance(entry["categories"], list)
    # The ports landed so far are listed.
    assert "supermami" in slugs
    assert "hiperlibertad" in slugs
    entry = next(entry for entry in entries if entry["slug"] == "supermami")
    assert entry["state"] == "idle"
    assert entry["categories"] == []
