"""Disco port (T9): offline fake-driver/fake-HTTP behavior.

Every test runs the ported scraper end to end against canned Selenium
driver data and canned json-LD HTML served by a fake HTTP session: exact
driver/HTTP request order, stored documents, progress messages and the
console output. The legacy-vs-port differential suite that used to
accompany these tests was removed with the legacy module in T14; the
examples here still pin the ported quirks (page 1 never collected, the
zero-total skip, the error and stop paths).
"""
import json
import threading
from types import SimpleNamespace

import pytest

from api.scrapers.base import ScrapeContext
from api.scrapers.disco import ScraperDisco

# -- canned scenario ---------------------------------------------------------
#
# Two bounded subcategories carry items; every other subcategory reads a
# total of 0 and is skipped without any HTTP request.
#
# total 61 -> range(2, int(61/20)+1) == range(2, 4) -> pages 2 and 3
# total 41 -> range(2, int(41/20)+1) == range(2, 3) -> page 2 only
SUB1 = "aceites-y-vinagres"
SUB2 = "aderezos"

SCROLL_SCRIPT = "window.scrollTo(0, document.body.scrollHeight/2);"
PAGE_1_URL = "https://www.disco.com.ar/almacen/" + SUB1


def page_url(seccion, i):
    return f'https://www.disco.com.ar/almacen/{seccion}?page={i}'


def ld_item(name, brand, sku, price):
    """One product in the shape Disco's embedded json-LD itemListElement has."""
    return {"item": {"name": name, "brand": {"name": brand}, "sku": sku,
                     "offers": {"lowPrice": price}}}


def jsonld_page(items):
    """A page whose product list lives in the embedded json-LD script.

    The script tag must follow the anchor div with NO whitespace between
    them: the scraper reads ``anchors[0].next``, the very next node in the
    parse tree, and skips the page unless it is a script tag.
    """
    payload = json.dumps({"itemListElement": items})
    return ('<html><body>'
            '<div class="flex flex-column min-vh-100 w-100">'
            '<script type="application/ld+json">' + payload + '</script>'
            '</div></body></html>')


def no_script_page():
    """A page whose anchor div is NOT followed by a script tag."""
    return ('<html><body>'
            '<div class="flex flex-column min-vh-100 w-100"><p>no json</p>'
            '</div></body></html>')


ITEM_A = ld_item("Aceite Girasol 900 ml", "Girasol", "1001", 1500.5)
ITEM_B = ld_item("Yerba Playadito 1 kg", "Playadito", "1002", 2500)
ITEM_C = ld_item("Mayonesa Hellmann's 500 gr", "Hellmann's", "1003", 999.99)
ITEM_D = ld_item("Arroz Gallo 1 kg", "Gallo", "1004", 800)


def expected_doc(name, unidad, brand, sku, price, categoria):
    """Stored shape as the repository persists it (scraped_at normalised away)."""
    return {"supermercado": "Disco", "name": name, "unidad": unidad,
            "brand": brand, "sku": sku, "price": price,
            "categoria": categoria}


HAPPY_PAGES = {
    page_url(SUB1, 2): jsonld_page([ITEM_A, ITEM_B]),
    page_url(SUB1, 3): jsonld_page([ITEM_C]),
}

# Stored shape after name_parse and the per-subcategory name sort.
EXPECTED_SUB1_DOCUMENTS = [
    expected_doc("Aceite Girasol", "900 ml", "Girasol", "1001", 1500.5, SUB1),
    expected_doc("Mayonesa Hellmann's", "500 gr", "Hellmann's", "1003",
                 999.99, SUB1),
    expected_doc("Yerba Playadito", "1 kg", "Playadito", "1002", 2500, SUB1),
]


def normalise(documents):
    return [{key: value for key, value in doc.items()
             if key not in ("_id", "scraped_at")}
            for doc in documents]


def stored_documents(repository):
    return normalise(repository.documents)


# -- fakes ------------------------------------------------------------------


class FakeDriver:
    """Recorder standing in for the Selenium Chrome driver.

    Serves a canned product total per subcategory (the last visited page-1
    URL decides which subcategory is being read) and records every call
    the port must reproduce.
    """

    def __init__(self, totals, *, on_script=None, get_error=None):
        self.totals = totals
        self.on_script = on_script
        self.get_error = get_error
        self.urls = []
        self.scripts = []
        self.maximized = False
        self.implicit_waits = []
        self.quit_count = 0

    def maximize_window(self):
        self.maximized = True

    def implicitly_wait(self, seconds):
        self.implicit_waits.append(seconds)

    def get(self, url):
        if self.get_error is not None:
            raise self.get_error
        self.urls.append(url)

    def execute_script(self, script):
        self.scripts.append(script)
        if self.on_script is not None:
            self.on_script(script)

    def find_element(self, by, selector):
        seccion = self.urls[-1].rstrip("/").rsplit("/", 1)[-1]
        return SimpleNamespace(text=f"{self.totals.get(seccion, 0)} productos")

    def quit(self):
        self.quit_count += 1


class FakeResponse:
    def __init__(self, text):
        self.text = text
        # The legacy path calls response.html.arender(sleep=8) without ever
        # awaiting it; the fake's arender is a plain no-op for that path.
        self.html = SimpleNamespace(arender=lambda **kwargs: None)


class FakeSession:
    """Offline stand-in for the shared HTTP session; records every GET.

    Serves canned pages keyed by URL, can raise on selected URLs (to
    exercise the per-page except) and can flip a stop event on the
    n-th request (to exercise the page-loop stop).
    """

    def __init__(self, pages, *, stop_event=None, flip_stop_on=None,
                 errors=None):
        self.urls = []
        self._pages = dict(pages)
        self._stop_event = stop_event
        self._flip_stop_on = flip_stop_on
        self._errors = dict(errors or {})

    def get(self, url):
        if (self._stop_event is not None
                and len(self.urls) == self._flip_stop_on):
            self._stop_event.set()
        self.urls.append(url)
        if url in self._errors:
            raise self._errors[url]
        if url not in self._pages:
            raise AssertionError(f"unexpected GET: {url}")
        return FakeResponse(self._pages[url])


@pytest.fixture(autouse=True)
def fast_sleep(monkeypatch):
    """Neutralise the real 5 s waits: unit tests never sleep in real time.

    ``ScrapeContext.sleep`` is the real-time seam, patched to record each
    requested duration and return ``should_stop()`` — False unless the
    test itself raised the stop, which keeps the stop-during-sleep break
    path meaningful without any real wait.
    """
    recorder = SimpleNamespace(requests=[])

    def fake_sleep(self, seconds):
        recorder.requests.append(seconds)
        return self.should_stop()

    monkeypatch.setattr(ScrapeContext, "sleep", fake_sleep)
    return recorder


def make_ctx(session, repository, *, driver=None, stop_event=None):
    messages: list[str] = []
    ctx = ScrapeContext(
        slug=ScraperDisco.slug, label=ScraperDisco.label,
        category="almacen", stop_event=stop_event or threading.Event(),
        report=messages.append, repository=repository,
        browser_factory=(lambda: driver) if driver is not None else None,
        http_factory=lambda: session)
    return ctx, messages


class OneSubcategoryScraper(ScraperDisco):
    """Bounds the run to a single subcategory so tests stay focused."""

    SUBCATEGORIES = (SUB1,)


class TwoSubcategoryScraper(ScraperDisco):
    """Bounds the run to two subcategories."""

    SUBCATEGORIES = (SUB1, SUB2)


# -- 1. happy path: driver calls, URLs, documents, messages -------------------


def test_full_run_visits_the_page_and_stores_the_sorted_documents(
        repository, fast_sleep):
    driver = FakeDriver({SUB1: 61})
    session = FakeSession(HAPPY_PAGES)
    ctx, messages = make_ctx(session, repository, driver=driver)

    OneSubcategoryScraper().run(ctx)

    assert driver.maximized is True
    assert driver.implicit_waits == [50]
    # The driver loaded the page-1 URL and executed the legacy scroll.
    assert driver.urls == [PAGE_1_URL]
    assert driver.scripts == [SCROLL_SCRIPT]
    # The 5 s wait was requested through the context, not time.sleep.
    assert fast_sleep.requests == [5]
    # Page 1 is never collected (legacy quirk, decision 1).
    assert session.urls == [page_url(SUB1, 2), page_url(SUB1, 3)]
    # Documents are name-sorted before saving (Cafe-style ordering).
    assert stored_documents(repository) == EXPECTED_SUB1_DOCUMENTS
    assert repository.calls == [("Disco", SUB1, None, 3)]
    assert driver.quit_count == 1
    assert messages == [
        f"Scrapeando subcategoría: {SUB1}",
        f"{SUB1} - página 2",
        f"{SUB1} - página 3",
        f"Guardados 3 productos de {SUB1} en base de datos",
        "PROCESO TERMINADO - Todas las subcategorías procesadas",
    ]


def test_page_one_is_never_collected(repository, fast_sleep):
    """Decision 1: the paging loop starts at ?page=2 and the page-1 HTML the
    driver loaded is never parsed, so page 1 products are missing from every
    Disco scrape. The mechanical port keeps the quirk; fixing it is a
    separate, real-run-validated follow-up (see the module docstring)."""
    driver = FakeDriver({SUB1: 61, SUB2: 41})
    session = FakeSession({**HAPPY_PAGES,
                           page_url(SUB2, 2): jsonld_page([ITEM_D])})
    ctx, _ = make_ctx(session, repository, driver=driver)

    TwoSubcategoryScraper().run(ctx)

    # Every requested page URL starts at ?page=2; ?page=1 never appears.
    assert session.urls == [page_url(SUB1, 2), page_url(SUB1, 3),
                            page_url(SUB2, 2)]
    assert not any(url.endswith("page=1") for url in session.urls)


def test_full_run_keeps_the_legacy_console_progress(repository, capsys):
    driver = FakeDriver({SUB1: 61})
    ctx, _ = make_ctx(FakeSession(HAPPY_PAGES), repository, driver=driver)

    OneSubcategoryScraper().run(ctx)

    console = capsys.readouterr().out
    assert f"Total de productos en {SUB1}: 61" in console
    assert f"scraping data from Disco - {SUB1} pagina: 2" in console
    assert f"scraping data from Disco - {SUB1} pagina: 3" in console
    assert f"Procesada subcategoría {SUB1} con 3 productos" in console
    assert "Proceso Disco terminado OK" in console


# -- 2. total == 0 ------------------------------------------------------------


def test_zero_total_skips_the_subcategory_without_http_or_save(
        repository, capsys):
    driver = FakeDriver({SUB1: 0})
    session = FakeSession({})  # any GET would fail loudly
    ctx, messages = make_ctx(session, repository, driver=driver)

    OneSubcategoryScraper().run(ctx)

    assert session.urls == []
    assert repository.calls == []
    assert repository.documents == []
    assert driver.quit_count == 1
    assert f"No hay productos en {SUB1}, continuando..." \
        in capsys.readouterr().out
    # The run still ends with the legacy final message.
    assert messages[-1] == "PROCESO TERMINADO - Todas las subcategorías procesadas"


# -- 3. stop -----------------------------------------------------------------


def test_stop_during_paging_saves_what_was_collected_and_quits(repository):
    stop_event = threading.Event()
    driver = FakeDriver({SUB1: 61})
    session = FakeSession({**HAPPY_PAGES,
                           page_url(SUB1, 3): jsonld_page([ITEM_C])},
                          stop_event=stop_event, flip_stop_on=0)
    ctx, messages = make_ctx(session, repository, driver=driver,
                             stop_event=stop_event)

    OneSubcategoryScraper().run(ctx)

    # Page 2 was fetched, page 3 never was: the stop honoured at the top of
    # the page loop ended the paging.
    assert session.urls == [page_url(SUB1, 2)]
    # What page 2 collected is still saved (name-sorted on its own).
    assert repository.calls == [("Disco", SUB1, None, 2)]
    assert stored_documents(repository) == [
        EXPECTED_SUB1_DOCUMENTS[0], EXPECTED_SUB1_DOCUMENTS[2]]
    # The context manager always quits the driver.
    assert driver.quit_count == 1


def test_stop_during_the_five_second_wait_ends_the_run_cleanly(repository):
    stop_event = threading.Event()
    driver = FakeDriver({SUB1: 61}, on_script=lambda script: stop_event.set())
    session = FakeSession({})  # any GET would fail loudly
    ctx, messages = make_ctx(session, repository, driver=driver,
                             stop_event=stop_event)

    OneSubcategoryScraper().run(ctx)

    # The stop raised during the wait broke out before any HTTP request or
    # total read; nothing was collected, nothing saved, driver still quit.
    assert driver.urls == [PAGE_1_URL]
    assert session.urls == []
    assert repository.calls == []
    assert driver.quit_count == 1
    assert messages == [
        f"Scrapeando subcategoría: {SUB1}",
        "PROCESO TERMINADO - Todas las subcategorías procesadas",
    ]


# -- 4. no-script anchor ------------------------------------------------------


def test_no_script_anchor_skips_the_page_and_the_run_continues(
        repository, capsys):
    driver = FakeDriver({SUB1: 61})
    session = FakeSession({page_url(SUB1, 2): no_script_page(),
                           page_url(SUB1, 3): jsonld_page([ITEM_A])})
    ctx, _ = make_ctx(session, repository, driver=driver)

    OneSubcategoryScraper().run(ctx)

    assert "No se encontró script en la página" in capsys.readouterr().out
    # The offending page was skipped but the run continued to page 3.
    assert session.urls == [page_url(SUB1, 2), page_url(SUB1, 3)]
    assert repository.calls == [("Disco", SUB1, None, 1)]


# -- 5. error handling --------------------------------------------------------


def test_unexpected_driver_errors_propagate_and_still_quit(repository):
    """Decision 2: the legacy outer ``except Exception`` printed and
    returned, so a broken run looked successful. The port lets unexpected
    exceptions escape (the manager marks the run ``failed``); the driver
    still gets quit by the context manager."""
    driver = FakeDriver({SUB1: 61}, get_error=RuntimeError("driver exploded"))
    ctx, _ = make_ctx(FakeSession({}), repository, driver=driver)

    with pytest.raises(RuntimeError, match="driver exploded"):
        OneSubcategoryScraper().run(ctx)

    assert driver.quit_count == 1


def test_page_level_error_is_reported_and_the_run_continues(repository,
                                                            capsys):
    """The legacy per-page ``try/except`` stays: the offending page is
    printed and reported, the run moves on, the rest is still saved."""
    driver = FakeDriver({SUB1: 61})
    session = FakeSession({page_url(SUB1, 2): jsonld_page([ITEM_A])},
                          errors={page_url(SUB1, 3):
                                  RuntimeError("page 3 exploded")})
    ctx, messages = make_ctx(session, repository, driver=driver)

    OneSubcategoryScraper().run(ctx)

    console = capsys.readouterr().out
    assert "Error al cargar la pagina 3: page 3 exploded" in console
    assert f"Error al cargar la pagina: 3" in messages
    # Page 2's product is still saved despite page 3 failing.
    assert repository.calls == [("Disco", SUB1, None, 1)]


