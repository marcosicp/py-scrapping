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


# -- generated aliases for the real slug (T7: SuperMami is ported) ------------


def test_default_registry_contains_supermami():
    """The alias routes below exist in the real app because default_registry()
    registers a ``supermami`` scraper; the behavioral tests inject a fake
    scraper with that slug so no real scrape is ever launched."""
    from api.scrapers.registry import default_registry
    registry = default_registry()
    assert "supermami" in registry
    assert registry.get("supermami").label == "SuperMami"


def test_post_scraping_supermami_starts_the_run(scraper_app_factory):
    entered = threading.Event()
    release = threading.Event()

    app = scraper_app_factory(make_scraper(
        "supermami", "SuperMami", make_blocking_run(entered, release)))
    client = app.test_client()
    try:
        # ``categories == ()``: any category value is accepted and ignored.
        response = client.post("/scraping-supermami",
                               query_string={"category": "cualquiera"})
        assert response.status_code == 200
        assert response.get_json() == {"success": True}
        assert entered.wait(TIMEOUT)
    finally:
        release.set()


def test_second_scraping_supermami_start_while_running_is_conflict(
        scraper_app_factory):
    entered = threading.Event()
    release = threading.Event()

    app = scraper_app_factory(make_scraper(
        "supermami", "SuperMami", make_blocking_run(entered, release)))
    client = app.test_client()
    try:
        assert client.post("/scraping-supermami").status_code == 200
        assert entered.wait(TIMEOUT)

        again = client.post("/scraping-supermami")
        assert again.status_code == 409
        assert again.get_json()["success"] is False
        assert again.get_json()["code"] == "already_running"
    finally:
        release.set()


def test_scraping_supermami_stop_accepts_get_and_post(scraper_app_factory):
    entered = threading.Event()
    release = threading.Event()

    app = scraper_app_factory(make_scraper(
        "supermami", "SuperMami", make_blocking_run(entered, release)))
    manager = app.extensions[EXTENSION_KEY].scrapers
    client = app.test_client()

    assert client.post("/scraping-supermami").status_code == 200
    assert entered.wait(TIMEOUT)
    stopped = client.get("/scraping-supermami-stop")
    assert stopped.status_code == 200
    assert stopped.get_json() == {"success": True}
    assert manager.wait("supermami", timeout=TIMEOUT).state is RunState.STOPPED


def test_scraping_supermami_stop_when_not_running_is_conflict(
        scraper_app_factory):
    app = scraper_app_factory(make_scraper("supermami", "SuperMami",
                                           lambda self, ctx: None))
    response = app.test_client().get("/scraping-supermami-stop")
    assert response.status_code == 409
    assert response.get_json()["success"] is False
    assert response.get_json()["code"] == "not_running"


# -- generated aliases for the real slug (T8: HiperLibertad is ported) --------


def test_default_registry_contains_hiperlibertad():
    """The alias routes below exist in the real app because default_registry()
    registers a ``hiperlibertad`` scraper; the behavioral tests inject a fake
    scraper with that slug so no real scrape is ever launched."""
    from api.scrapers.registry import default_registry
    registry = default_registry()
    assert "hiperlibertad" in registry
    assert registry.get("hiperlibertad").label == "HiperLibertad"


def test_post_scraping_hiperlibertad_starts_the_run(scraper_app_factory):
    entered = threading.Event()
    release = threading.Event()

    app = scraper_app_factory(make_scraper(
        "hiperlibertad", "HiperLibertad", make_blocking_run(entered, release),
        categories=("almacen",)))
    client = app.test_client()
    try:
        response = client.post("/scraping-hiperlibertad",
                               query_string={"category": "almacen"})
        assert response.status_code == 200
        assert response.get_json() == {"success": True}
        assert entered.wait(TIMEOUT)
    finally:
        release.set()


def test_second_scraping_hiperlibertad_start_while_running_is_conflict(
        scraper_app_factory):
    entered = threading.Event()
    release = threading.Event()

    app = scraper_app_factory(make_scraper(
        "hiperlibertad", "HiperLibertad", make_blocking_run(entered, release),
        categories=("almacen",)))
    client = app.test_client()
    try:
        assert client.post("/scraping-hiperlibertad").status_code == 200
        assert entered.wait(TIMEOUT)

        again = client.post("/scraping-hiperlibertad")
        assert again.status_code == 409
        assert again.get_json()["success"] is False
        assert again.get_json()["code"] == "already_running"
    finally:
        release.set()


def test_scraping_hiperlibertad_stop_accepts_get_and_post(
        scraper_app_factory):
    entered = threading.Event()
    release = threading.Event()

    app = scraper_app_factory(make_scraper(
        "hiperlibertad", "HiperLibertad", make_blocking_run(entered, release),
        categories=("almacen",)))
    manager = app.extensions[EXTENSION_KEY].scrapers
    client = app.test_client()

    # First run: stop via GET.
    assert client.post("/scraping-hiperlibertad").status_code == 200
    assert entered.wait(TIMEOUT)
    stopped = client.get("/scraping-hiperlibertad-stop")
    assert stopped.status_code == 200
    assert stopped.get_json() == {"success": True}
    assert manager.wait("hiperlibertad",
                        timeout=TIMEOUT).state is RunState.STOPPED

    # Second run: stop via POST.
    entered.clear()
    release.clear()
    assert client.post("/scraping-hiperlibertad").status_code == 200
    assert entered.wait(TIMEOUT)
    stopped = client.post("/scraping-hiperlibertad-stop")
    assert stopped.status_code == 200
    assert stopped.get_json() == {"success": True}
    assert manager.wait("hiperlibertad",
                        timeout=TIMEOUT).state is RunState.STOPPED


def test_scraping_hiperlibertad_stop_when_not_running_is_conflict(
        scraper_app_factory):
    app = scraper_app_factory(make_scraper("hiperlibertad", "HiperLibertad",
                                           lambda self, ctx: None))
    response = app.test_client().get("/scraping-hiperlibertad-stop")
    assert response.status_code == 409
    assert response.get_json()["success"] is False
    assert response.get_json()["code"] == "not_running"


# -- generated aliases for the real slug (T9: Disco is ported) ----------------


def test_default_registry_contains_disco():
    """The alias routes below exist in the real app because default_registry()
    registers a ``disco`` scraper; the behavioral tests inject a fake
    scraper with that slug so no real scrape is ever launched."""
    from api.scrapers.registry import default_registry
    registry = default_registry()
    assert "disco" in registry
    assert registry.get("disco").label == "Disco"


def test_post_scraping_disco_starts_the_run(scraper_app_factory):
    entered = threading.Event()
    release = threading.Event()

    app = scraper_app_factory(make_scraper(
        "disco", "Disco", make_blocking_run(entered, release),
        categories=("almacen",)))
    client = app.test_client()
    try:
        response = client.post("/scraping-disco",
                               query_string={"category": "almacen"})
        assert response.status_code == 200
        assert response.get_json() == {"success": True}
        assert entered.wait(TIMEOUT)
    finally:
        release.set()


def test_second_scraping_disco_start_while_running_is_conflict(
        scraper_app_factory):
    entered = threading.Event()
    release = threading.Event()

    app = scraper_app_factory(make_scraper(
        "disco", "Disco", make_blocking_run(entered, release),
        categories=("almacen",)))
    client = app.test_client()
    try:
        assert client.post("/scraping-disco").status_code == 200
        assert entered.wait(TIMEOUT)

        again = client.post("/scraping-disco")
        assert again.status_code == 409
        assert again.get_json()["success"] is False
        assert again.get_json()["code"] == "already_running"
    finally:
        release.set()


def test_scraping_disco_stop_accepts_get_and_post(scraper_app_factory):
    entered = threading.Event()
    release = threading.Event()

    app = scraper_app_factory(make_scraper(
        "disco", "Disco", make_blocking_run(entered, release),
        categories=("almacen",)))
    manager = app.extensions[EXTENSION_KEY].scrapers
    client = app.test_client()

    # First run: stop via GET.
    assert client.post("/scraping-disco").status_code == 200
    assert entered.wait(TIMEOUT)
    stopped = client.get("/scraping-disco-stop")
    assert stopped.status_code == 200
    assert stopped.get_json() == {"success": True}
    assert manager.wait("disco", timeout=TIMEOUT).state is RunState.STOPPED

    # Second run: stop via POST.
    entered.clear()
    release.clear()
    assert client.post("/scraping-disco").status_code == 200
    assert entered.wait(TIMEOUT)
    stopped = client.post("/scraping-disco-stop")
    assert stopped.status_code == 200
    assert stopped.get_json() == {"success": True}
    assert manager.wait("disco", timeout=TIMEOUT).state is RunState.STOPPED


def test_scraping_disco_stop_when_not_running_is_conflict(
        scraper_app_factory):
    app = scraper_app_factory(make_scraper("disco", "Disco",
                                           lambda self, ctx: None))
    response = app.test_client().get("/scraping-disco-stop")
    assert response.status_code == 409
    assert response.get_json()["success"] is False
    assert response.get_json()["code"] == "not_running"


def test_no_legacy_rule_exists_for_an_unregistered_slug(scraper_app_factory):
    app = scraper_app_factory(make_scraper("fake", "Fake",
                                           lambda self, ctx: None))
    rules = {rule.rule for rule in app.url_map.iter_rules()}
    assert "/scraping-fake" in rules
    assert "/scraping-fake-stop" in rules
    assert "/scraping-ghost" not in rules
    assert "/scraping-ghost-stop" not in rules
