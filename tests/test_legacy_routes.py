"""Legacy ``/scraping-<slug>`` aliases generated from the registry (D7)."""
import threading

from api.container import EXTENSION_KEY
from api.services.scraping import RunState
from tests.fakes import make_scraper

TIMEOUT = 5.0


def make_blocking_run(entered=None, release=None):
    def run(self, ctx):
        if entered is not None:
            entered.set()
        while not (release.is_set() or ctx.should_stop()):
            ctx.sleep(0.01)
    return run


def test_post_scraping_alias_starts_the_run(scraper_app_factory):
    entered = threading.Event()
    release = threading.Event()

    app = scraper_app_factory(make_scraper(
        "fake", "Fake", make_blocking_run(entered, release)))
    client = app.test_client()
    try:
        response = client.post("/scraping-fake")
        assert response.status_code == 200
        assert response.get_json() == {"success": True}
        assert entered.wait(TIMEOUT)
    finally:
        release.set()


def test_second_start_while_running_is_conflict(scraper_app_factory):
    entered = threading.Event()
    release = threading.Event()

    app = scraper_app_factory(make_scraper(
        "fake", "Fake", make_blocking_run(entered, release)))
    client = app.test_client()
    try:
        assert client.post("/scraping-fake").status_code == 200
        assert entered.wait(TIMEOUT)

        again = client.post("/scraping-fake")
        assert again.status_code == 409
        assert again.get_json()["success"] is False
        assert again.get_json()["code"] == "already_running"
    finally:
        release.set()


def test_stop_accepts_get_and_post(scraper_app_factory):
    entered = threading.Event()
    release = threading.Event()

    app = scraper_app_factory(make_scraper(
        "fake", "Fake", make_blocking_run(entered, release)))
    manager = app.extensions[EXTENSION_KEY].scrapers
    client = app.test_client()

    # First run: stop via GET.
    assert client.post("/scraping-fake").status_code == 200
    assert entered.wait(TIMEOUT)
    stopped = client.get("/scraping-fake-stop")
    assert stopped.status_code == 200
    assert stopped.get_json() == {"success": True}
    assert manager.wait("fake", timeout=TIMEOUT).state is RunState.STOPPED

    # Second run: stop via POST.
    entered.clear()
    release.clear()
    assert client.post("/scraping-fake").status_code == 200
    assert entered.wait(TIMEOUT)
    stopped = client.post("/scraping-fake-stop")
    assert stopped.status_code == 200
    assert stopped.get_json() == {"success": True}
    assert manager.wait("fake", timeout=TIMEOUT).state is RunState.STOPPED


def test_stop_when_not_running_is_conflict(scraper_app_factory):
    app = scraper_app_factory(make_scraper("fake", "Fake",
                                           lambda self, ctx: None))
    response = app.test_client().get("/scraping-fake-stop")
    assert response.status_code == 409
    assert response.get_json()["success"] is False
    assert response.get_json()["code"] == "not_running"


def test_invalid_category_is_400(scraper_app_factory):
    entered = threading.Event()
    release = threading.Event()

    def run(self, ctx):
        entered.set()
        while not (release.is_set() or ctx.should_stop()):
            ctx.sleep(0.01)

    app = scraper_app_factory(make_scraper(
        "fake", "Fake", run, categories=("almacen", "bebidas")))
    client = app.test_client()
    try:
        response = client.post("/scraping-fake", query_string={
            "category": "hogar"})
        assert response.status_code == 400
        body = response.get_json()
        assert body["success"] is False
        assert body["code"] == "invalid_category"
        assert body["allowed"] == ["almacen", "bebidas"]
        # Nothing started.
        status = client.get("/api/scrapers/fake").get_json()
        assert status["state"] == "idle"
    finally:
        release.set()


def test_no_legacy_rule_exists_for_an_unregistered_slug(scraper_app_factory):
    app = scraper_app_factory(make_scraper("fake", "Fake",
                                           lambda self, ctx: None))
    rules = {rule.rule for rule in app.url_map.iter_rules()}
    assert "/scraping-fake" in rules
    assert "/scraping-fake-stop" in rules
    assert "/scraping-ghost" not in rules
    assert "/scraping-ghost-stop" not in rules
