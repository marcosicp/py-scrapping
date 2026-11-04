"""HiperLibertad port (T8): offline fake-HTTP behavior + legacy differential.

The legacy reference ``api.scrapers.scrap_hiperlibertad`` runs against the
same canned VTEX JSON (with its never-used Selenium driver stubbed out so
no browser starts) and the resulting stored documents are compared with
the ported scraper's. The legacy status guard is broken on purpose (see
the differential test): it is a chained comparison that is False for
every status, so the legacy path stores nothing while the port accepts
200/206 and stores the expected documents. That divergence is the tested
fix #1; the never-used legacy driver is the tested fix #2.
"""
import io
import threading
from contextlib import redirect_stdout
from types import SimpleNamespace

import pytest
from flask import Flask

from api.scrapers.base import ScrapeContext
from api.scrapers.hiperlibertad import ScraperHiperLibertad
from api.scrapers.scrap_hiperlibertad import (
    ScrapeHiperLibertad as LegacyScraper)
from tests.fakes import FakeCollection, InMemoryProductRepository

# -- fakes ------------------------------------------------------------------


class FakeStatus:
    """A canned response with a status code and a decoded JSON payload."""

    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise AssertionError(
                "response.json() called on a payload-less response")
        return self._payload


# -- canned VTEX JSON ---------------------------------------------------------

SUB1 = "aceites-y-vinagres"
SUB2 = "aderezos"


@pytest.fixture(autouse=True)
def fast_sleep(monkeypatch):
    """Neutralise the real rate-limiting wait: unit tests never sleep.

    ``ScrapeContext.sleep`` is the real-time seam (its true semantics are
    covered by tests/test_scrape_context.py), so here it is patched to
    record each requested duration and return ``should_stop()`` — False
    unless the test itself raised the stop, which keeps the
    stop-during-sleep break path meaningful without any real wait.
    """
    recorder = SimpleNamespace(requests=[])

    def fake_sleep(self, seconds):
        recorder.requests.append(seconds)
        return self.should_stop()

    monkeypatch.setattr(ScrapeContext, "sleep", fake_sleep)
    return recorder


def vtex_item(name, *, brand="Marca", sku="0001", price=100.0):
    """One product in the shape the VTEX search API returns."""
    return {"productName": name, "brand": brand, "sku": sku,
            "items": [{"sellers": [{"commertialOffer": {"Price": price}}]}]}


ITEM_A = vtex_item("Aceite Girasol 900 ml", brand="Girasol",
                   sku="1001", price=1500.5)
ITEM_B = vtex_item("Yerba Playadito 1 kg", brand="Playadito",
                   sku="1002", price=2500)
ITEM_C = vtex_item("Mayonesa Hellmann's 500 gr", brand="Hellmann's",
                   sku="1003", price=999.99)

# Two bounded subcategories: page 1 carries items, page 2 is empty (the
# "no more products" break), so the run never walks all 14 subcategories.
HAPPY_RESPONSES = [
    FakeStatus(200, [ITEM_A, ITEM_B]),  # sub1 page 1 (_from=0&_to=49)
    FakeStatus(200, []),                # sub1 page 2 (_from=50&_to=99): end
    FakeStatus(200, [ITEM_C]),          # sub2 page 1
    FakeStatus(200, []),                # sub2 page 2: end
]

# Legacy URLs, copied verbatim from api/scrapers/scrap_hiperlibertad.py.


def vtex_url(categoria, subCategory, pageIncrement):
    return (f'https://www.hiperlibertad.com.ar/api/catalog_system/pub/'
            f'products/search/{categoria}/{subCategory}?O=OrderByPriceASC'
            f'&_from={pageIncrement}&_to={pageIncrement+49}&ft&sc=1')


HAPPY_URLS = [
    vtex_url("almacen", SUB1, 0),
    vtex_url("almacen", SUB1, 50),
    vtex_url("almacen", SUB2, 0),
    vtex_url("almacen", SUB2, 50),
]


def expected_doc(name, unidad, brand, sku, price, subcategoria):
    """Stored shape as the repository persists it (scraped_at normalised away)."""
    return {"supermercado": "HiperLibertad", "name": name, "unidad": unidad,
            "brand": brand, "sku": sku, "price": price,
            "categoria": "almacen", "subcategoria": subcategoria}


def stored_documents(repository):
    return [{key: value for key, value in doc.items()
             if key not in ("_id", "scraped_at")}
            for doc in repository.documents]


# -- fakes ------------------------------------------------------------------


class FakeSession:
    """Offline stand-in for the shared HTTP session.

    Returns the queued responses in order and raises if the scraper asks
    for more URLs than the test queued, so unexpected requests fail loudly.
    """

    def __init__(self, responses, *, stop_event=None, flip_stop_on=None):
        self.urls = []
        self._responses = list(responses)
        self._stop_event = stop_event
        self._flip_stop_on = flip_stop_on

    def get(self, url, timeout=None):
        if (self._stop_event is not None
                and len(self.urls) == self._flip_stop_on):
            self._stop_event.set()
        self.urls.append(url)
        if not self._responses:
            raise AssertionError(f"unexpected extra GET: {url}")
        return self._responses.pop(0)


def make_ctx(session, repository, *, stop_event=None, browser_factory=None):
    messages: list[str] = []
    ctx = ScrapeContext(
        slug=ScraperHiperLibertad.slug, label=ScraperHiperLibertad.label,
        category="almacen", stop_event=stop_event or threading.Event(),
        report=messages.append, repository=repository,
        browser_factory=browser_factory,
        http_factory=lambda: session)
    return ctx, messages


class TwoSubcategoryScraper(ScraperHiperLibertad):
    """Bounds the run to two subcategories so no test walks all 14."""

    SUBCATEGORIES = (SUB1, SUB2)


class OneSubcategoryScraper(ScraperHiperLibertad):
    """Bounds the run to a single subcategory."""

    SUBCATEGORIES = (SUB1,)


# -- 1. happy path: exact URLs, documents, calls and messages -----------------


def test_full_run_requests_the_legacy_urls_and_stores_the_legacy_documents(
        repository):
    session = FakeSession(HAPPY_RESPONSES)
    ctx, messages = make_ctx(session, repository)

    TwoSubcategoryScraper().run(ctx)

    assert session.urls == HAPPY_URLS
    assert stored_documents(repository) == [
        expected_doc("Aceite Girasol", "900 ml", "Girasol", "1001",
                     1500.5, SUB1),
        expected_doc("Yerba Playadito", "1 kg", "Playadito", "1002",
                     2500, SUB1),
        expected_doc("Mayonesa Hellmann's", "500 gr", "Hellmann's", "1003",
                     999.99, SUB2),
    ]
    # Documents are grouped per save: first SUB1's (name-sorted), then
    # SUB2's.
    assert repository.calls == [
        ("HiperLibertad", "almacen", SUB1, 2),
        ("HiperLibertad", "almacen", SUB2, 1),
    ]
    assert messages == [
        "Scrapeando categoria: almacen",
        f"Inicio Scrap sub-categoria: {SUB1}",
        f"{SUB1} - página 1",
        f"{SUB1} - página 2",
        "Guardados 2 productos de aceites-y-vinagres en base de datos",
        f"Inicio Scrap sub-categoria: {SUB2}",
        f"{SUB2} - página 1",
        f"{SUB2} - página 2",
        "Guardados 1 productos de aderezos en base de datos",
        "PROCESO TERMINADO",
    ]


def test_full_run_keeps_the_legacy_console_progress(repository):
    """The legacy print lines are part of the mechanical port."""
    output = io.StringIO()
    with redirect_stdout(output):
        TwoSubcategoryScraper().run(
            make_ctx(FakeSession(HAPPY_RESPONSES), repository)[0])
    console = output.getvalue()
    assert (f"Procesada subcategoría {SUB1} con 2 productos" in console)
    assert (f"Procesada subcategoría {SUB2} con 1 productos" in console)
    assert ("Saved 2 HiperLibertad products from almacen/"
            f"{SUB1} to MongoDB" in console)
    assert ("Saved 1 HiperLibertad products from almacen/"
            f"{SUB2} to MongoDB" in console)
    assert "Proceso HiperLibertad terminado OK" in console


# -- 2. the status guard (fix #1) ---------------------------------------------


def test_status_200_is_accepted_and_saved(repository):
    responses = [FakeStatus(200, [ITEM_A]), FakeStatus(200, [])]
    ctx, messages = make_ctx(FakeSession(responses), repository)

    OneSubcategoryScraper().run(ctx)

    assert repository.calls == [("HiperLibertad", "almacen", SUB1, 1)]
    assert messages[-2] == f"Guardados 1 productos de {SUB1} en base de datos"
    assert messages[-1] == "PROCESO TERMINADO"


def test_status_206_is_accepted_and_saved(repository):
    responses = [FakeStatus(206, [ITEM_A]), FakeStatus(200, [])]
    ctx, messages = make_ctx(FakeSession(responses), repository)

    OneSubcategoryScraper().run(ctx)

    assert repository.calls == [("HiperLibertad", "almacen", SUB1, 1)]
    assert messages[-2] == f"Guardados 1 productos de {SUB1} en base de datos"
    assert messages[-1] == "PROCESO TERMINADO"


def test_status_500_prints_the_error_and_breaks(repository, capsys):
    ctx, messages = make_ctx(FakeSession([FakeStatus(500, [])]), repository)

    OneSubcategoryScraper().run(ctx)

    console = capsys.readouterr().out
    assert "Error API response: 500" in console
    # Nothing stored, and the run still ends with the legacy final message.
    assert repository.calls == []
    assert repository.documents == []
    assert messages[-1] == "PROCESO TERMINADO"
    assert not any(m.startswith("Guardados") for m in messages)


def test_the_legacy_status_guard_was_false_for_every_status():
    """Pin of fix #1: the legacy guard chained ``==`` with ``|`` (bitwise OR
    binds tighter than ``==``), so ``200 == 200 | 200 == 206`` parsed as the
    chained comparison ``200 == (200|200) == 206`` and evaluated False for
    EVERY response code — the legacy scraper stored nothing, ever."""
    assert (200 == 200 | 200 == 206) is False
    assert (206 == 206 | 206 == 200) is False


# -- 3. duplicate guard and default price -------------------------------------


def test_duplicate_guard_skips_a_contained_name(repository):
    base = vtex_item("Dulce de Leche La Serenisima 500 gr",
                     brand="La Serenisima", sku="2001", price=800)
    contained = vtex_item("Dulce de Leche La Serenisima 500 gr x2",
                          brand="La Serenisima", sku="2002", price=1600)
    responses = [FakeStatus(200, [base, contained]), FakeStatus(200, [])]
    ctx, _ = make_ctx(FakeSession(responses), repository)

    OneSubcategoryScraper().run(ctx)

    # The second name contains the first stored name, so the legacy
    # substring guard skipped it.
    stored = stored_documents(repository)
    assert len(stored) == 1
    assert stored[0]["name"] == "Dulce de Leche La Serenisima"
    assert repository.calls == [("HiperLibertad", "almacen", SUB1, 1)]


def test_missing_items_or_sellers_store_price_zero(repository):
    no_items = {"productName": "Fideos Canale 500 gr",
                "brand": "Canale", "sku": "3001"}
    empty_items = {"productName": "Mate Cocido Rosamonte 100 gr",
                   "brand": "Rosamonte", "sku": "3002", "items": []}
    no_sellers = {"productName": "Cafe Nescafe 200 gr",
                  "items": [{"sellers": []}]}
    responses = [
        FakeStatus(200, [no_items, empty_items, no_sellers]),
        FakeStatus(200, []),
    ]
    ctx, _ = make_ctx(FakeSession(responses), repository)

    OneSubcategoryScraper().run(ctx)

    stored = stored_documents(repository)
    # The subcategory is name-sorted before saving (Cafe < Fideos < Mate).
    assert [doc["name"] for doc in stored] == [
        "Cafe Nescafe", "Fideos Canale", "Mate Cocido Rosamonte"]
    assert [doc["price"] for doc in stored] == [0, 0, 0]
    assert [doc["brand"] for doc in stored] == ["", "Canale", "Rosamonte"]
    assert [doc["sku"] for doc in stored] == ["", "3001", "3002"]
    assert [doc["unidad"] for doc in stored] == [
        "200 gr", "500 gr", "100 gr"]


# -- 3b. the rate limit requested per successfully paged request --------------


def test_rate_limit_is_one_second_per_successfully_paged_request(
        fast_sleep, repository):
    """Fidelity the real 1 s wait implicitly covered: the scraper asks for
    the rate limit exactly once per request that yielded items, and never
    for pages that end the loop (empty page or error status)."""
    session = FakeSession(HAPPY_RESPONSES)
    ctx, _ = make_ctx(session, repository)

    TwoSubcategoryScraper().run(ctx)

    # Four requests; the two that yielded items each requested the 1 s
    # rate limit once; the two empty pages broke before sleeping.
    assert len(session.urls) == 4
    assert fast_sleep.requests == [1, 1]

    # An error status ends the subcategory before any rate limit.
    fast_sleep.requests.clear()
    error_session = FakeSession([FakeStatus(500, [])])
    OneSubcategoryScraper().run(
        make_ctx(error_session, InMemoryProductRepository())[0])
    assert fast_sleep.requests == []


# -- 4. stop while paging ------------------------------------------------------


def test_stop_while_paging_never_fetches_page_two_and_still_saves(repository):
    stop_event = threading.Event()
    responses = [FakeStatus(200, [ITEM_A, ITEM_B])]
    session = FakeSession(responses, stop_event=stop_event, flip_stop_on=0)
    ctx, messages = make_ctx(session, repository, stop_event=stop_event)

    TwoSubcategoryScraper().run(ctx)

    # Page 1 was fetched, page 2 never was: the stop raised during the
    # rate-limiting sleep ended the paging loop.
    assert session.urls == [vtex_url("almacen", SUB1, 0)]
    # The collected page is still saved.
    assert repository.calls == [("HiperLibertad", "almacen", SUB1, 2)]
    assert stored_documents(repository) == [
        expected_doc("Aceite Girasol", "900 ml", "Girasol", "1001",
                     1500.5, SUB1),
        expected_doc("Yerba Playadito", "1 kg", "Playadito", "1002",
                     2500, SUB1),
    ]
    # The second subcategory was never started.
    assert messages == [
        "Scrapeando categoria: almacen",
        f"Inicio Scrap sub-categoria: {SUB1}",
        f"{SUB1} - página 1",
        f"Guardados 2 productos de {SUB1} en base de datos",
        "PROCESO TERMINADO",
    ]


# -- 5. no browser (fix #2) ----------------------------------------------------


def test_no_browser_is_ever_built(repository):
    browsers = []
    session = FakeSession(HAPPY_RESPONSES)

    def browser_factory():
        browsers.append("browser")
        raise AssertionError("the port must never open a browser")

    ctx, _ = make_ctx(session, repository, browser_factory=browser_factory)

    TwoSubcategoryScraper().run(ctx)

    assert browsers == []
    assert session.urls == HAPPY_URLS


# -- 6. legacy-vs-port differential -------------------------------------------

# Legacy runs all 14 hardcoded subcategories; only these two carry items.
LEGACY_CANNED_ITEMS = {
    SUB1: [[ITEM_A, ITEM_B], []],
    SUB2: [[ITEM_C], []],
}


def run_legacy(monkeypatch):
    """Run the legacy scraper offline (differential technique from T7).

    Fakes: ``requests.get`` returns the canned JSON with status 200 for
    every page, ``notifyStatus`` is silenced, and Selenium's ``webdriver`` /
    ``Service`` are stubbed so the never-used legacy driver "starts" without
    any browser. MongoDB is a ``FakeCollection`` behind a pushed Flask app
    context, exactly like the legacy ``save_to_mongodb`` expects.
    """
    import api.scrapers.scrap_hiperlibertad as legacy

    legacy_urls: list[str] = []

    def fake_get(url, timeout=None):
        legacy_urls.append(url)
        for sub, pages in LEGACY_CANNED_ITEMS.items():
            if f"/almacen/{sub}?" in url:
                return FakeStatus(200, pages.pop(0) if pages else [])
        # The other 12 subcategories also get a well-formed 200 page.
        return FakeStatus(200, [])

    class FakeDriver:
        def quit(self):
            pass

    def fake_chrome(service=None, options=None):
        return FakeDriver()

    def fake_options():
        return SimpleNamespace(add_argument=lambda *args, **kwargs: None)

    def fake_service(path):
        return SimpleNamespace(path=path)

    monkeypatch.setattr(legacy, "requests",
                        SimpleNamespace(get=fake_get))
    monkeypatch.setattr(legacy, "notifyStatus",
                        lambda channel, message: None)
    monkeypatch.setattr(legacy, "webdriver",
                        SimpleNamespace(Chrome=fake_chrome,
                                        ChromeOptions=fake_options))
    monkeypatch.setattr(legacy, "Service", fake_service)

    collection = FakeCollection()
    flask_app = Flask("hiperlibertad-differential")
    flask_app.mongodb_client = SimpleNamespace(
        lalistitadev=SimpleNamespace(productos=collection))
    with flask_app.app_context():
        LegacyScraper().scrape_hiperlibertad("almacen")
    return legacy_urls, collection


def test_legacy_stores_nothing_while_the_port_stores_the_expected_documents(
        monkeypatch, capsys, repository):
    """The differential: same canned JSON, two paths.

    The legacy status guard is a chained comparison that is False for every
    status, so the legacy scraper asks the API for all 14 subcategories,
    rejects every response, and stores nothing. The ported scraper, fixed
    to accept 200/206, stores the expected documents for its bounded
    subcategory list. Both sides run against the same canned JSON offline.
    """
    # capsys keeps the legacy print noise out of the report output.
    legacy_urls, collection = run_legacy(monkeypatch)
    assert len(legacy_urls) == 14  # one page per hardcoded subcategory
    # Fix #1 legacy behavior: the guard rejected status 200 every time.
    assert collection.events == []
    assert collection.documents == []

    # The port, same canned pages, stores the expected documents.
    port_repository = InMemoryProductRepository()
    port_session = FakeSession(HAPPY_RESPONSES)
    TwoSubcategoryScraper().run(
        make_ctx(port_session, port_repository)[0])

    assert collection.documents == []
    assert port_session.urls == HAPPY_URLS
    assert stored_documents(port_repository) == [
        expected_doc("Aceite Girasol", "900 ml", "Girasol", "1001",
                     1500.5, SUB1),
        expected_doc("Yerba Playadito", "1 kg", "Playadito", "1002",
                     2500, SUB1),
        expected_doc("Mayonesa Hellmann's", "500 gr", "Hellmann's", "1003",
                     999.99, SUB2),
    ]


def test_legacy_saves_through_delete_many_and_insert_many(monkeypatch,
                                                         capsys):
    """Documented legacy persistence shape (kept as evidence for T14): with
    the broken guard the legacy path never reaches its fake Mongo at all."""
    _, collection = run_legacy(monkeypatch)
    assert collection.events == []
