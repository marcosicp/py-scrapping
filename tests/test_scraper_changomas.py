"""ChangoMas port (T11): offline fake-driver/fake-HTTP behavior.

Every test runs the ported scraper end to end against canned Selenium data
and canned json-LD pages: exact driver/HTTP request order, stored documents,
progress messages and the console output. The legacy-vs-port differential
suite that used to accompany these tests was removed with the legacy module
in T14; the tests here still pin the ported quirks (the hardcoded
page-loop URL, the empty-results whole-run abort, the "PROCESO TERMINADO
CON 0 produtos" counter quirk, and the K-12 fix of never writing files).
"""
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

import api.scrapers.changomas as port_module
from api.scrapers.base import ScrapeContext
from api.scrapers.changomas import ScraperChangoMas

# -- canned scenario ---------------------------------------------------------
#
# Two sections are discovered from the driver; each one is visited once
# through the driver and its page loop re-fetches the DISCOVERY page over
# the shared HTTP session (the legacy re-fetch quirk, kept verbatim).

DISCOVERY_URL = "https://www.masonline.com.ar/3454?map=productClusterIds"
SECTION_URL_PREFIX = (
    "https://www.masonline.com.ar/268?initialMap=productClusterIds"
    "&initialQuery=268&map=category-1,productclusternames"
    "&query=/desayuno-y-golosinas/mas-online---almacen")
SCROLL_SCRIPT = "window.scrollTo(0, document.body.scrollHeight/2);"
TOTAL_CLASS = "vtex-search-result-3-x-totalProducts--layout"

SEC1 = "almacen/aceites"
SEC2 = "almacen/snacks"
HREF1 = "https://www.masonline.com.ar/" + SEC1
HREF2 = "https://www.masonline.com.ar/" + SEC2


def section_url(seccion):
    return SECTION_URL_PREFIX + seccion


def ld_item(name, price):
    """One product in the shape ChangoMas's embedded json-LD itemListElement has."""
    return {"item": {"name": name, "offers": {"lowPrice": price}}}


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


ITEM_A = ld_item("Aceite Girasol 900 ml", 1500.5)
ITEM_B = ld_item("Alfajor Jorgito 60 gr", 300)
ITEM_C = ld_item("Arroz Gallo 1 kg", 800)

# The page loop re-fetches the SAME discovery URL for every section; the
# fake session serves these pages in order, one per fetch.
DISCOVERY_PAGES = [jsonld_page([ITEM_A, ITEM_B]), jsonld_page([ITEM_C])]

RESULTS_COUNTS = {SEC1: 2, SEC2: 1}


def expected_doc(name, price, subcategoria):
    """Stored shape as the repository persists it (scraped_at normalised away)."""
    return {"supermercado": "ChangoMas", "name": name, "price": price,
            "categoria": "almacen", "subcategoria": subcategoria}


# The stored subcategoria is the legacy fileName = seccion.split("/")[1].
EXPECTED_DOCUMENTS = [
    expected_doc("Aceite Girasol 900 ml", 1500.5, "aceites"),
    expected_doc("Alfajor Jorgito 60 gr", 300, "aceites"),
    expected_doc("Arroz Gallo 1 kg", 800, "snacks"),
]


def stored_documents(repository):
    return [{key: value for key, value in doc.items()
             if key not in ("_id", "scraped_at")}
            for doc in repository.documents]


# -- fakes -------------------------------------------------------------------


class FakeElement:
    """A ``categoryItem`` anchor exposing its href."""

    def __init__(self, href):
        self._href = href

    def get_attribute(self, name):
        assert name == "href"
        return self._href


class FakeSectionsRoot:
    """The ``categoryList-container__items`` container of the discovery page."""

    def __init__(self, driver):
        self._driver = driver

    def find_elements(self, by, selector):
        assert selector == "categoryItem"
        return [FakeElement(href) for href in self._driver.section_hrefs]


class FakeGalleryRoot:
    """The ``gallery-layout-container`` of the section page being visited.

    The result count is keyed by the section of the LAST visited driver URL,
    because the fake driver records its URL before the scraper reads it.
    """

    def __init__(self, driver):
        self._driver = driver

    def find_elements(self, by, selector):
        assert selector == "*"
        current = self._driver.urls[-1][len(SECTION_URL_PREFIX):]
        count = self._driver.results_counts.get(current, 0)
        return [object() for _ in range(count)]


class FakeDriver:
    """Recorder standing in for the Selenium Chrome driver.

    Records every call the port must reproduce; the ``total`` element is
    served from the (legacy-ignored) last visited section URL.
    """

    def __init__(self, section_hrefs, results_counts, *, on_get=None):
        self.section_hrefs = section_hrefs
        self.results_counts = results_counts
        self.on_get = on_get
        self.urls = []
        self.scripts = []
        self.maximized = False
        self.implicit_waits = []
        self.quit_count = 0
        self.close_count = 0

    def maximize_window(self):
        self.maximized = True

    def implicitly_wait(self, seconds):
        self.implicit_waits.append(seconds)

    def get(self, url):
        if self.on_get is not None:
            self.on_get(url)
        self.urls.append(url)

    def execute_script(self, script):
        self.scripts.append(script)

    def find_element(self, by, selector):
        assert selector == TOTAL_CLASS
        return SimpleNamespace(text="12 productos")

    def quit(self):
        self.quit_count += 1

    def close(self):
        self.close_count += 1


class FakeResponse:
    def __init__(self, text):
        self.text = text
        # The legacy path calls response.html.arender(sleep=8) without ever
        # awaiting it; the fake's arender is a plain no-op for that path.
        self.html = SimpleNamespace(arender=lambda **kwargs: None)


class FakeSession:
    """Offline stand-in for the shared HTTP session; records every GET.

    Serves canned pages keyed by URL; a list value is popped in order, so
    repeated fetches of the same URL (the legacy re-fetch quirk) can serve
    different pages. Anything else fails loudly.
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
        page = self._pages[url]
        if isinstance(page, list):
            assert page, f"exhausted canned pages for {url}"
            page = page.pop(0)
        return FakeResponse(page)


def make_fake_waits(driver):
    """Fake ``WebDriverWait`` / ``EC`` / ``By`` triple, offline.

    The fake EC resolves its locator lazily (the scraper wraps it in a
    ``WebDriverWait(...).until(...)`` call) against the shared fake driver.
    """

    class FakeWebDriverWait:
        def __init__(self, driver_, timeout):
            assert driver_ is driver

        def until(self, condition):
            return condition()

    class FakeEC:
        @staticmethod
        def visibility_of_all_elements_located(locator):
            def visible():
                if locator[1] == "categoryList-container__items":
                    return [FakeSectionsRoot(driver)]
                if locator[1] == "gallery-layout-container":
                    return [FakeGalleryRoot(driver)]
                raise AssertionError(f"unexpected wait locator: {locator!r}")
            return visible

    FakeBy = SimpleNamespace(CLASS_NAME="class name", ID="id", XPATH="xpath")
    return FakeWebDriverWait, FakeEC, FakeBy


@pytest.fixture(autouse=True)
def fast_sleep(monkeypatch):
    """Neutralise the real 5 s waits: unit tests never sleep in real time.

    ``ScrapeContext.sleep`` is the real-time seam, patched to record each
    requested duration and return ``should_stop()`` — False unless the
    test itself raised the stop, which keeps the stop paths meaningful
    without any real wait.
    """
    recorder = SimpleNamespace(requests=[])

    def fake_sleep(self, seconds):
        recorder.requests.append(seconds)
        return self.should_stop()

    monkeypatch.setattr(ScrapeContext, "sleep", fake_sleep)
    return recorder


@pytest.fixture(autouse=True)
def no_file_writes(monkeypatch):
    """Fail loudly if ANYTHING opens a file for writing (the K-12 guard).

    The port persists through the repository, so no run may ever touch the
    ``.changomas/`` dump directory the original implementation wrote to.
    """
    real_open = open

    def guard(file, mode="r", *args, **kwargs):
        if mode and any(flag in mode for flag in "wax+"):
            raise AssertionError(
                f"unexpected file write: {file!r} mode={mode!r}")
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr("builtins.open", guard)


def patch_waits(monkeypatch, driver):
    """Point the port's lazy selenium import at the fake triple."""
    monkeypatch.setattr(port_module, "_selenium_waits",
                        lambda: make_fake_waits(driver))


def make_ctx(session, repository, *, driver, stop_event=None):
    messages: list[str] = []
    built: list = []

    def browser_factory():
        built.append("browser")
        return driver

    ctx = ScrapeContext(
        slug=ScraperChangoMas.slug, label=ScraperChangoMas.label,
        category=None, stop_event=stop_event or threading.Event(),
        report=messages.append, repository=repository,
        browser_factory=browser_factory, http_factory=lambda: session)
    return ctx, messages, built


# -- 1. happy path ------------------------------------------------------------


def test_happy_path_visits_sections_saves_documents_and_never_writes_files(
        monkeypatch, repository, fast_sleep, capsys):
    driver = FakeDriver([HREF1, HREF2], RESULTS_COUNTS)
    session = FakeSession({DISCOVERY_URL: list(DISCOVERY_PAGES)})
    patch_waits(monkeypatch, driver)

    ctx, messages, built = make_ctx(session, repository, driver=driver)

    ScraperChangoMas().run(ctx)

    # The driver visited the discovery page and one page per section.
    assert driver.urls == [DISCOVERY_URL, section_url(SEC1), section_url(SEC2)]
    assert driver.scripts == [SCROLL_SCRIPT, SCROLL_SCRIPT]
    assert driver.maximized is True
    assert driver.implicit_waits == [50]
    assert built == ["browser"]
    # The 5 s waits are requested through the context, not time.sleep:
    # one after the discovery visit, one per section.
    assert fast_sleep.requests == [5, 5, 5]
    # One HTTP fetch per section (the legacy re-fetch quirk).
    assert session.urls == [DISCOVERY_URL, DISCOVERY_URL]
    # Documents saved per section, sorted by name, with the section-derived
    # subcategoria.
    assert repository.calls == [
        ("ChangoMas", "almacen", "aceites", 2),
        ("ChangoMas", "almacen", "snacks", 1),
    ]
    assert stored_documents(repository) == EXPECTED_DOCUMENTS
    # No filesystem write anywhere (K-12): the guard fixture would have
    # raised, and the legacy dump directory must not exist after the run.
    assert Path(".changomas").exists() is False
    # The legacy final message is kept verbatim; jsondata was cleared after
    # each per-section save, so the reported count is the legacy 0.
    assert messages[-1] == "PROCESO TERMINADO CON 0 productos"
    output = capsys.readouterr().out
    assert "secciones 2" in output
    assert output.count("Chirp") == 3
    assert "Proceso changomas termino OK, con 0 productos" in output


def test_page_loop_fetches_the_hardcoded_discovery_url(monkeypatch, repository,
                                                      fast_sleep):
    """Legacy quirk kept verbatim (commented at the code): the page loop
    re-fetches the DISCOVERY page, not the section page, before parsing the
    json-LD. The fake session serves a different canned page per fetch, so
    both sections collect their own items from that one URL."""
    driver = FakeDriver([HREF1], {SEC1: 2})
    session = FakeSession({DISCOVERY_URL: [jsonld_page([ITEM_A, ITEM_B])]})
    patch_waits(monkeypatch, driver)
    ctx, _, built = make_ctx(session, repository, driver=driver)

    ScraperChangoMas().run(ctx)

    assert session.urls == [DISCOVERY_URL]
    assert driver.urls == [DISCOVERY_URL, section_url(SEC1)]
    assert repository.calls == [("ChangoMas", "almacen", "aceites", 2)]
    assert built == ["browser"]


# -- 2. the whole-run abort ---------------------------------------------------


def test_empty_results_abort_the_whole_run_before_any_save(monkeypatch,
                                                           fast_sleep):
    """Legacy ``if results.__len__() == 0: return`` kept verbatim: the WHOLE
    run ends — no HTTP fetch, no save, no final report, no second section."""
    repository = InMemoryRepository()
    driver = FakeDriver([HREF1, HREF2], {SEC1: 0, SEC2: 3})
    session = FakeSession({DISCOVERY_URL: list(DISCOVERY_PAGES)})
    patch_waits(monkeypatch, driver)
    ctx, messages, _ = make_ctx(session, repository, driver=driver)

    ScraperChangoMas().run(ctx)

    assert driver.urls == [DISCOVERY_URL, section_url(SEC1)]
    assert session.urls == []
    assert repository.calls == []
    assert not any(m.startswith("PROCESO TERMINADO") for m in messages)


# -- 3. cooperative stop ------------------------------------------------------


def test_stop_ends_the_page_loop_saves_collected_sections_and_quits_driver(
        monkeypatch, fast_sleep):
    stop_event = threading.Event()
    repository = InMemoryRepository()
    driver = FakeDriver([HREF1, HREF2], RESULTS_COUNTS)
    # The stop is raised while the first section's page fetch is in flight:
    # that section still saves; the second section's page loop stops before
    # fetching anything.
    session = FakeSession({DISCOVERY_URL: list(DISCOVERY_PAGES)},
                          stop_event=stop_event, flip_stop_on=0)
    patch_waits(monkeypatch, driver)
    ctx, _, _ = make_ctx(session, repository, driver=driver,
                         stop_event=stop_event)

    ScraperChangoMas().run(ctx)

    # The page loop stopped: only ONE http fetch happened.
    assert session.urls == [DISCOVERY_URL]
    # Both sections were still visited (the stop only breaks the page loop).
    assert driver.urls == [DISCOVERY_URL, section_url(SEC1), section_url(SEC2)]
    # The collected section stayed saved; the empty one saved nothing.
    assert repository.calls == [("ChangoMas", "almacen", "aceites", 2)]
    # The driver is still quit through the context manager.
    assert driver.quit_count == 1


# -- 4. decision 2: unexpected errors propagate -------------------------------


def test_driver_errors_propagate_and_the_driver_is_still_quit(monkeypatch,
                                                                 fast_sleep):
    """The legacy outer ``except Exception`` printed and returned, so a
    broken run looked successful. The ported run lets errors escape (the
    same decision 2 the other ports took) — the manager marks it failed."""
    repository = InMemoryRepository()

    class ExplodingDriver(FakeDriver):
        def get(self, url):
            if url != DISCOVERY_URL:
                raise RuntimeError("driver exploded on " + url)
            super().get(url)

    driver = ExplodingDriver([HREF1], RESULTS_COUNTS)
    session = FakeSession({DISCOVERY_URL: list(DISCOVERY_PAGES)})
    patch_waits(monkeypatch, driver)
    ctx, _, _ = make_ctx(session, repository, driver=driver)

    with pytest.raises(RuntimeError, match="driver exploded"):
        ScraperChangoMas().run(ctx)

    assert driver.quit_count == 1


def test_page_loop_http_error_is_swallowed_like_the_legacy(monkeypatch,
                                                           fast_sleep):
    """The legacy per-page ``except Exception: continue`` is kept verbatim:
    a failing page fetch skips to the next iteration instead of ending the
    run."""
    repository = InMemoryRepository()
    driver = FakeDriver([HREF1], {SEC1: 2})
    session = FakeSession({}, errors={DISCOVERY_URL: RuntimeError("boom")})
    patch_waits(monkeypatch, driver)
    ctx, messages, _ = make_ctx(session, repository, driver=driver)

    ScraperChangoMas().run(ctx)

    assert repository.calls == []
    assert messages[-1] == "PROCESO TERMINADO CON 0 productos"
    assert driver.quit_count == 1


# -- local fakes --------------------------------------------------------------


class InMemoryRepository:
    """Thin local wrapper so abort/stop/error tests need no fixture wiring."""

    def __init__(self):
        self.documents: list[dict] = []
        self.calls: list[tuple] = []

    def replace_products(self, supermercado, products, *, categoria=None,
                         subcategoria=None):
        if not products:
            return 0
        self.documents.extend(dict(p) for p in products)
        self.calls.append((supermercado, categoria, subcategoria,
                           len(products)))
        return len(products)


