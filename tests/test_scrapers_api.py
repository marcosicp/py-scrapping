"""HTTP contract of the scraper-control API under /api/scrapers.

Every fake scraper synchronizes through ``threading.Event`` handshakes and
``ScraperManager.wait`` joins; ``time.sleep`` is never used for ordering.
"""
import threading

from api.container import EXTENSION_KEY
from api.services.scraping import RunState
from tests.fakes import make_scraper

TIMEOUT = 5.0
STATUS_KEYS = {
    "slug", "label", "state", "active", "category",
    "started_at", "finished_at", "message", "saved", "categories",
}


def make_blocking_run(entered=None, saved_event=None, release=None):
    """A run that reports, optionally saves, then waits to be released.

    The loop exits cooperatively on ``ctx.should_stop()`` so a teardown stop
    releases the thread even if the test crashed before its own release.
    """
    def run(self, ctx):
        ctx.report("scanning")
        ctx.save([{"name": "pan", "price": 10}])
        if saved_event is not None:
            saved_event.set()
        while not (release.is_set() or ctx.should_stop()):
            ctx.sleep(0.01)
        ctx.report("done")
    if entered:
        entered.set()
    return run


def idle_view(client, slug):
    response = client.get(f"/api/scrapers/{slug}")
    assert response.status_code == 200
    return response.get_json()


# -- listing, status and unknown slugs ------------------------------------

def test_list_shows_every_registered_scraper_in_order_with_categories(
        scraper_app_factory):
    app = scraper_app_factory(
        make_scraper("aa", "AA", lambda self, ctx: None),
        make_scraper("bb", "BB", lambda self, ctx: None,
                     categories=("almacen", "bebidas")),
    )
    response = app.test_client().get("/api/scrapers")
    assert response.status_code == 200
    scrapers = response.get_json()["scrapers"]
    assert [s["slug"] for s in scrapers] == ["aa", "bb"]
    for entry in scrapers:
        assert entry["state"] == "idle"
        assert entry["active"] is False
    assert scrapers[0]["label"] == "AA"
    assert scrapers[0]["categories"] == []
    assert scrapers[1]["categories"] == ["almacen", "bebidas"]


def test_get_status_of_an_idle_scraper(scraper_app_factory):
    app = scraper_app_factory(make_scraper("unit", "Unit",
                                           lambda self, ctx: None))
    client = app.test_client()
    body = idle_view(client, "unit")
    assert body["slug"] == "unit"
    assert body["state"] == "idle"
    assert body["finished_at"] is None


def test_unknown_slug_is_404_on_get_start_and_stop(scraper_app_factory):
    client = scraper_app_factory().test_client()
    response = client.get("/api/scrapers/ghost")
    assert response.status_code == 404
    assert response.get_json()["code"] == "unknown_scraper"
    assert "ghost" in response.get_json()["error"]

    started = client.post("/api/scrapers/ghost/start")
    assert started.status_code == 404
    assert started.get_json()["code"] == "unknown_scraper"

    stopped = client.post("/api/scrapers/ghost/stop")
    assert stopped.status_code == 404
    assert stopped.get_json()["code"] == "unknown_scraper"


def test_status_payload_uses_the_documented_keys(scraper_app_factory):
    app = scraper_app_factory(make_scraper("unit", "Unit",
                                           lambda self, ctx: None))
    body = idle_view(app.test_client(), "unit")
    assert set(body) == STATUS_KEYS


# -- starting -------------------------------------------------------------

def test_start_runs_and_persists_then_succeeds(scraper_app_factory):
    saved_event = threading.Event()
    release = threading.Event()

    app = scraper_app_factory(make_scraper(
        "work", "Work", make_blocking_run(saved_event=saved_event,
                                          release=release)))
    manager = app.extensions[EXTENSION_KEY].scrapers
    client = app.test_client()

    response = client.post("/api/scrapers/work/start")
    assert response.status_code == 202
    body = response.get_json()
    assert body["state"] == "running"
    assert body["active"] is True
    assert saved_event.wait(TIMEOUT)

    conflict = client.post("/api/scrapers/work/start")
    assert conflict.status_code == 409
    assert conflict.get_json()["code"] == "already_running"

    release.set()
    manager.wait("work", timeout=TIMEOUT)
    final = idle_view(client, "work")
    assert final["state"] == "succeeded"
    assert final["saved"] == 1
    assert final["finished_at"] is not None
    assert final["message"] == "done"


def test_category_via_query_string(scraper_app_factory):
    captured = {}
    entered = threading.Event()
    release = threading.Event()

    def run(self, ctx):
        captured["category"] = ctx.category
        entered.set()
        while not (release.is_set() or ctx.should_stop()):
            ctx.sleep(0.01)

    app = scraper_app_factory(make_scraper(
        "cat", "Cat", run, categories=("almacen", "bebidas")))
    client = app.test_client()
    try:
        response = client.post("/api/scrapers/cat/start?category=almacen")
        assert response.status_code == 202
        assert response.get_json()["category"] == "almacen"
        assert entered.wait(TIMEOUT)
        assert captured["category"] == "almacen"
    finally:
        release.set()


def test_category_via_json_body(scraper_app_factory):
    captured = {}
    entered = threading.Event()
    release = threading.Event()

    def run(self, ctx):
        captured["category"] = ctx.category
        entered.set()
        while not (release.is_set() or ctx.should_stop()):
            ctx.sleep(0.01)

    app = scraper_app_factory(make_scraper(
        "cat", "Cat", run, categories=("almacen", "bebidas")))
    client = app.test_client()
    try:
        response = client.post("/api/scrapers/cat/start",
                               json={"category": "bebidas"})
        assert response.status_code == 202
        assert response.get_json()["category"] == "bebidas"
        assert entered.wait(TIMEOUT)
        assert captured["category"] == "bebidas"
    finally:
        release.set()


def test_invalid_category_is_400_and_nothing_starts(scraper_app_factory):
    release = threading.Event()
    app = scraper_app_factory(make_scraper(
        "cat", "Cat", make_blocking_run(release=release),
        categories=("almacen", "bebidas")))
    client = app.test_client()
    try:
        response = client.post("/api/scrapers/cat/start?category=hogar")
        assert response.status_code == 400
        body = response.get_json()
        assert body["code"] == "invalid_category"
        assert body["allowed"] == ["almacen", "bebidas"]
        assert idle_view(client, "cat")["state"] == "idle"
    finally:
        release.set()


def test_scraper_without_categories_ignores_the_value(scraper_app_factory):
    captured = {}
    entered = threading.Event()
    release = threading.Event()

    def run(self, ctx):
        captured["category"] = ctx.category
        entered.set()
        while not (release.is_set() or ctx.should_stop()):
            ctx.sleep(0.01)

    app = scraper_app_factory(make_scraper("free", "Free", run))
    client = app.test_client()
    try:
        response = client.post("/api/scrapers/free/start?category=whatever")
        assert response.status_code == 202
        assert response.get_json()["category"] is None
        assert entered.wait(TIMEOUT)
        assert captured["category"] is None
    finally:
        release.set()


# -- stopping ---------------------------------------------------------------

def test_stop_a_running_scraper(scraper_app_factory):
    release = threading.Event()
    app = scraper_app_factory(make_scraper(
        "loopy", "Loopy", make_blocking_run(release=release)))
    manager = app.extensions[EXTENSION_KEY].scrapers
    client = app.test_client()

    assert client.post("/api/scrapers/loopy/start").status_code == 202
    response = client.post("/api/scrapers/loopy/stop")
    assert response.status_code == 202
    assert response.get_json()["state"] == "stopping"

    status = manager.wait("loopy", timeout=TIMEOUT)
    assert status.state is RunState.STOPPED
    assert idle_view(client, "loopy")["state"] == "stopped"


def test_stop_an_idle_scraper_is_409(scraper_app_factory):
    app = scraper_app_factory(make_scraper("unit", "Unit",
                                           lambda self, ctx: None))
    response = app.test_client().post("/api/scrapers/unit/stop")
    assert response.status_code == 409
    assert response.get_json()["code"] == "not_running"


# -- concurrency and failure --------------------------------------------------------

def test_two_scrapers_run_concurrently_and_independently(scraper_app_factory):
    entered_one, entered_two = threading.Event(), threading.Event()
    release_one, release_two = threading.Event(), threading.Event()

    app = scraper_app_factory(
        make_scraper("one", "One", make_blocking_run(entered_one,
                                                     release=release_one)),
        make_scraper("two", "Two", make_blocking_run(entered_two,
                                                     release=release_two)),
    )
    manager = app.extensions[EXTENSION_KEY].scrapers
    client = app.test_client()
    try:
        start_one = client.post("/api/scrapers/one/start")
        start_two = client.post("/api/scrapers/two/start")
        assert start_one.status_code == 202
        assert start_two.status_code == 202
        # Both threads must be alive at the same time before either ends.
        assert entered_one.wait(TIMEOUT)
        assert entered_two.wait(TIMEOUT)
        assert idle_view(client, "one")["state"] == "running"
        assert idle_view(client, "two")["state"] == "running"
        assert idle_view(client, "one")["slug"] == "one"
        assert idle_view(client, "two")["state"] != "idle"

        release_one.set()
        assert manager.wait(
            "one", timeout=TIMEOUT).state is RunState.SUCCEEDED
        # The other run was untouched by one's finish.
        assert manager.status("two").state is RunState.RUNNING

        release_two.set()
        assert manager.wait(
            "two", timeout=TIMEOUT).state is RunState.SUCCEEDED
    finally:
        release_one.set()
        release_two.set()


def test_a_failing_scraper_ends_failed_with_the_error_text(
        scraper_app_factory):
    def run(self, ctx):
        ctx.report("about to fail")
        raise ValueError("boom")

    app = scraper_app_factory(make_scraper("bomb", "Bomb", run))
    manager = app.extensions[EXTENSION_KEY].scrapers
    client = app.test_client()

    assert client.post("/api/scrapers/bomb/start").status_code == 202
    manager.wait("bomb", timeout=TIMEOUT)
    body = idle_view(client, "bomb")
    assert body["state"] == "failed"
    assert "ValueError: boom" in body["message"]
    assert body["finished_at"] is not None
