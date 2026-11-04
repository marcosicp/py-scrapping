"""Carrefour port (T10): offline fake-driver/fake-HTTP behavior.

Every test runs the ported scraper end to end against canned pages: exact
driver/HTTP request order, stored documents, progress messages and the
console output. The legacy-vs-port differential suite that used to
accompany these tests was removed with the legacy module in T14; the
tests here still pin the ported quirks for BOTH collection paths:

- Path A (a category was requested): json-LD ``template`` extraction over
  the HTTP session, documents WITHOUT ``unidad``, no browser at all, and
  the ``total == 0`` abort of the whole run.
- Path B (no category): driver visits, ``render-provider`` script JSON,
  documents WITH ``unidad``, one save per category, plus the empty-result
  no-op keep-slice behavior on Path A.
"""
import json
import threading
from types import SimpleNamespace

import pytest

from api.scrapers.base import ScrapeContext
from api.scrapers.carrefour import ScraperCarrefour

# -- canned scenario ---------------------------------------------------------
#
# total 49 -> range(1, int(49/16)) == range(1, 3) -> pages 1 and 2
# total 33 -> range(1, int(33/16)) == range(1, 2) -> page 1 only
# total 65 -> range(1, int(65/16)) == range(1, 4) -> pages 1, 2 and 3
SUB1 = "aceites-y-vinagres"        # almacen
SUB2 = "snacks"                    # almacen
SUB3 = "cafe"                      # desayuno-y-merienda
SUB_EMPTY = "arroz-y-legumbres"    # almacen (total 0 in the skip test)

SCROLL_SCRIPT = "window.scrollTo(0, document.body.scrollHeight);"
TOTAL_CLASS_A = "valtech-carrefourar-search-result-0-x-totalProducts--layout"


def base_url(categoria, subCategory):
    return f"https://www.carrefour.com.ar/{categoria}/{subCategory}"


def page_url(categoria, subCategory, i):
    return f"https://www.carrefour.com.ar/{categoria}/{subCategory}?page={i}"


def ld_item(name, brand, sku, price):
    """One product in the shape Carrefour's embedded json-LD itemListElement has."""
    return {"item": {"name": name, "brand": {"name": brand}, "sku": sku,
                     "offers": {"lowPrice": price}}}


def base_page(total):
    """A page-1 body whose product total lives in the totalProducts element."""
    return ('<html><body>'
            f'<div class="{TOTAL_CLASS_A}">{total} productos</div>'
            '</body></html>')


def template_page(items):
    """A page whose product list lives in the embedded json-LD template.

    The script tag must follow the template tag with NO whitespace between
    them: the scraper reads ``anchors[0].next``, the very next node in the
    parse tree, and skips the page unless it is a script tag.
    """
    payload = json.dumps({"itemListElement": items})
    return ('<html><body>'
            '<template data-type="json" data-varname="__STATE__">'
            '<script type="application/ld+json">' + payload + '</script>'
            '</template></body></html>')


def no_template_page():
    """A page with no json-LD template at all."""
    return '<html><body><p>no json here</p></body></html>'


def template_without_script_page():
    """A page whose template tag is NOT followed by a script tag."""
    return ('<html><body>'
            '<template data-type="json" data-varname="__STATE__">'
            '<p>no json</p>'
            '</template></body></html>')


# -- Path A items (raw: no name_parse, no unidad — legacy omission) -----------
ITEM_A = ld_item("Aceite Girasol 900 ml", "Girasol", "1001", 1500.5)
ITEM_B = ld_item("Yerba Playadito 1 kg", "Playadito", "1002", 2500)
ITEM_C = ld_item("Mayonesa Hellmann's 500 gr", "Hellmann's", "1003", 999.99)

# -- Path B items (parsed: name_parse splits name/unidad) ---------------------
B_A = ld_item("Aceite Girasol 900 ml", "Girasol", "1001", 1500.5)
B_B = ld_item("Yerba Playadito 1 kg", "Playadito", "1002", 2500)
B_C = ld_item("Mayonesa Hellmann's 500 gr", "Hellmann's", "1003", 999.99)
B_D = ld_item("Arroz Gallo 1 kg", "Gallo", "1004", 800)
B_E = ld_item("Café Mercedolas 500 gr", "Mercedolas", "1005", 1200)
B_F = ld_item("Alfajor Jorgito 60 gr", "Jorgito", "1006", 300)
B_G = ld_item("Mermelada Arcor 450 gr", "Arcor", "1007", 950)
B_DUP = ld_item("Café Mercedolas 1 kg", "Mercedolas", "1005", 1150)


def expected_doc_a(name, brand, sku, price):
    """Stored Path A shape: raw name, no unidad (legacy omission kept)."""
    return {"supermercado": "Carrefour", "name": name, "brand": brand,
            "sku": sku, "price": price, "categoria": "almacen"}


def expected_doc_b(name, unidad, brand, sku, price, categoria):
    """Stored Path B shape: name_parse split the unit out of the name."""
    return {"supermercado": "Carrefour", "name": name, "unidad": unidad,
            "brand": brand, "sku": sku, "price": price, "categoria": categoria}


def stored_documents(repository):
    return [{key: value for key, value in doc.items()
             if key not in ("_id", "scraped_at")}
            for doc in repository.documents]


# -- fakes ------------------------------------------------------------------


def _split_url(url):
    """(categoria, subCategory) out of a base or ?page= URL."""
    path = url.split("//", 1)[1].split("?", 1)[0]
    _, categoria, subCategory = path.split("/", 2)
    return categoria, subCategory


class FakeDriver:
    """Recorder standing in for the Selenium Chrome driver.

    Serves the canned product total per (categoria, subCategory) for the
    totalProducts element and the canned script JSON per (categoria,
    subCategory, page) for the render-provider element; records every call
    the port must reproduce. Every other subcategory reads a total of 0.
    """

    def __init__(self, totals=None, pages=None, *, on_get=None):
        self.totals = totals or {}
        self.pages = pages or {}
        self.on_get = on_get
        self.urls = []
        self.scripts = []
        self.quit_count = 0
        self.switch_to = SimpleNamespace(window=lambda handle: None)
        self.current_window_handle = "window-1"

    def get(self, url):
        self.urls.append(url)
        if self.on_get is not None:
            self.on_get(url)

    def execute_script(self, script):
        self.scripts.append(script)

    def find_element(self, by, selector):
        categoria, subCategory = _split_url(self.urls[-1])
        if "totalProducts--layout" in selector:
            total = self.totals.get((categoria, subCategory), 0)
            return SimpleNamespace(text=f"{total} productos")
        if selector == '//div[@class="render-provider"]':
            page = int(self.urls[-1].rsplit("page=", 1)[-1])
            payload = json.dumps(
                {"itemListElement": self.pages[(categoria, subCategory, page)]})
            return SimpleNamespace(find_element=lambda by, using:
                                   SimpleNamespace(get_attribute=lambda name:
                                                   payload))
        raise AssertionError(f"unexpected find_element: {selector}")

    def quit(self):
        self.quit_count += 1


class FakeResponse:
    def __init__(self, text):
        self.text = text


class FakeSession:
    """Offline stand-in for the shared HTTP session; records every GET.

    Serves canned pages keyed by URL and raises loudly on anything else, so
    a stray request fails the test instead of passing silently.
    """

    def __init__(self, pages):
        self.urls = []
        self._pages = dict(pages)

    def get(self, url):
        self.urls.append(url)
        if url not in self._pages:
            raise AssertionError(f"unexpected GET: {url}")
        return FakeResponse(self._pages[url])


@pytest.fixture(autouse=True)
def fast_sleep(monkeypatch):
    """Neutralise the real 10 s waits: unit tests never sleep in real time.

    ``ScrapeContext.sleep`` is the real-time seam, patched to record each
    requested duration and return ``should_stop()`` — False unless the test
    itself raised the stop, which keeps the stop paths meaningful without
    any real wait.
    """
    recorder = SimpleNamespace(requests=[])

    def fake_sleep(self, seconds):
        recorder.requests.append(seconds)
        return self.should_stop()

    monkeypatch.setattr(ScrapeContext, "sleep", fake_sleep)
    return recorder


def make_ctx(session, repository, *, category=None, driver=None,
             stop_event=None):
    """Build a ScrapeContext that counts every browser build (Path A builds none)."""
    messages: list[str] = []
    built: list = []

    def browser_factory():
        built.append("browser")
        if driver is None:
            raise AssertionError("no browser expected")
        return driver

    ctx = ScrapeContext(
        slug=ScraperCarrefour.slug, label=ScraperCarrefour.label,
        category=category, stop_event=stop_event or threading.Event(),
        report=messages.append, repository=repository,
        browser_factory=browser_factory, http_factory=lambda: session)
    return ctx, messages, built


class OneSubcategoryScraper(ScraperCarrefour):
    """Bounds Path A / Path B to almacen/[SUB1] so tests stay focused."""

    CATEGORIES = ({"categoria": "almacen", "subcategorias": [SUB1]},)


class TwoSubcategoryScraper(ScraperCarrefour):
    """Bounds Path A to almacen/[SUB1, SUB2]."""

    CATEGORIES = ({"categoria": "almacen", "subcategorias": [SUB1, SUB2]},)


class TwoCategoryScraper(ScraperCarrefour):
    """Bounds Path B to one subcategory per category."""

    CATEGORIES = (
        {"categoria": "almacen", "subcategorias": [SUB1]},
        {"categoria": "desayuno-y-merienda", "subcategorias": [SUB3]},
    )


class EmptyFirstScraper(ScraperCarrefour):
    """Bounds Path B to almacen/[SUB_EMPTY, SUB1]."""

    CATEGORIES = ({"categoria": "almacen",
                   "subcategorias": [SUB_EMPTY, SUB1]},)


# -- Path A: a category was requested (json-LD over the HTTP session) ---------


def test_path_a_visits_pages_and_stores_documents_without_unidad(
        repository, fast_sleep, capsys):
    session = FakeSession({
        base_url("almacen", SUB1): base_page(49),
        page_url("almacen", SUB1, 1): template_page([ITEM_A, ITEM_B]),
        page_url("almacen", SUB1, 2): template_page([ITEM_C]),
    })
    ctx, messages, built = make_ctx(session, repository, category="almacen",
                                    driver=None)
    scraper = OneSubcategoryScraper()
    scraper.CATEGORIES = ({"categoria": "almacen", "subcategorias": [SUB1]},)

    scraper.run(ctx)

    # No driver built at all: Path A is pure HTTP.
    assert built == []
    # The legacy visited page 1 through the driver (same URL the port GETs)
    # and fetched ?page=1..N over the HTTP session; the port keeps the exact
    # URL sequence: base, ?page=1, ?page=2.
    assert session.urls == [base_url("almacen", SUB1),
                            page_url("almacen", SUB1, 1),
                            page_url("almacen", SUB1, 2)]
    # The legacy 10 s page-1 wait is kept.
    assert fast_sleep.requests == [10]
    # Documents WITHOUT unidad and WITHOUT name_parse (legacy omission kept).
    assert stored_documents(repository) == [
        expected_doc_a("Aceite Girasol 900 ml", "Girasol", "1001", 1500.5),
        expected_doc_a("Yerba Playadito 1 kg", "Playadito", "1002", 2500),
        expected_doc_a("Mayonesa Hellmann's 500 gr", "Hellmann's", "1003",
                       999.99),
    ]
    assert repository.calls == [("Carrefour", "almacen", None, 3)]
    assert messages == [
        "Scrapeando categoria: almacen",
        "Inicio Scrap sub-categoria: aceites-y-vinagres",
        "1-49",
        "2-49",
        "Guardados 3 productos de almacen en base de datos",
    ]
    # The legacy console noise ('Chirp' per appended item) is kept.
    assert capsys.readouterr().out.count("Chirp") == 3


def test_path_a_zero_total_aborts_the_whole_run_before_saving(repository,
                                                              fast_sleep):
    """Legacy ``if total == 0: return`` kept verbatim: the WHOLE run ends
    before any save and before the remaining subcategories are touched."""
    session = FakeSession({
        base_url("almacen", SUB1): base_page(0),
        # SUB2 must never be requested: the abort happens on SUB1.
        base_url("almacen", SUB2): base_page(49),
    })
    ctx, messages, built = make_ctx(session, repository, category="almacen",
                                    driver=None)

    TwoSubcategoryScraper().run(ctx)

    assert session.urls == [base_url("almacen", SUB1)]
    assert repository.calls == []
    assert repository.documents == []
    assert built == []
    assert messages == [
        "Scrapeando categoria: almacen",
        "Inicio Scrap sub-categoria: aceites-y-vinagres",
    ]


def test_path_a_empty_result_keeps_the_stored_slice(repository, fast_sleep):
    """Decision 1: the legacy called save_to_mongodb unconditionally, which
    deleted the category and inserted nothing on a zero-product scrape. The
    port calls ctx.save([]) — a no-op (the D6 guarantee that fixed K-8) — so
    the pre-existing documents of that category survive."""
    repository.documents = [{"supermercado": "Carrefour",
                             "name": "Dulce de leche viejo",
                             "categoria": "almacen"}]
    session = FakeSession({
        base_url("almacen", SUB1): base_page(49),
        page_url("almacen", SUB1, 1): no_template_page(),
        page_url("almacen", SUB1, 2): no_template_page(),
    })
    ctx, messages, built = make_ctx(session, repository, category="almacen",
                                    driver=None)

    saved: list = []
    real_save = ctx.save

    def spy_save(products, **kwargs):
        saved.append(list(products))
        return real_save(products, **kwargs)

    ctx.save = spy_save

    OneSubcategoryScraper().run(ctx)

    # ctx.save([]) was called and the repository recorded NOTHING.
    assert saved == [[]]
    assert repository.calls == []
    # The pre-existing documents of the category survived.
    assert stored_documents(repository) == [
        {"supermercado": "Carrefour", "name": "Dulce de leche viejo",
         "categoria": "almacen"}]
    assert built == []


def test_path_a_template_without_script_breaks_the_page_loop(repository,
                                                             fast_sleep):
    """Legacy ``anchors[0].next.name != 'script'`` break kept verbatim: the
    remaining pages of the subcategory are never fetched."""
    session = FakeSession({
        base_url("almacen", SUB1): base_page(49),
        page_url("almacen", SUB1, 1): template_without_script_page(),
        # Page 2 carries items but must never be requested.
        page_url("almacen", SUB1, 2): template_page([ITEM_A]),
    })
    ctx, messages, built = make_ctx(session, repository, category="almacen",
                                    driver=None)

    OneSubcategoryScraper().run(ctx)

    assert session.urls == [base_url("almacen", SUB1),
                            page_url("almacen", SUB1, 1)]
    assert repository.calls == []
    assert built == []
    # The break skips the str(i)+"-"+str(total) report too (legacy verbatim).
    assert messages == [
        "Scrapeando categoria: almacen",
        "Inicio Scrap sub-categoria: aceites-y-vinagres",
    ]


# -- Path B: no category (driver + render-provider JSON) ----------------------


PATH_B_TOTALS = {("almacen", SUB1): 49,
                 ("desayuno-y-merienda", SUB3): 49}
PATH_B_PAGES = {
    ("almacen", SUB1, 1): [B_A, B_B],
    ("almacen", SUB1, 2): [B_C],
    ("desayuno-y-merienda", SUB3, 1): [B_E, B_F],
    ("desayuno-y-merienda", SUB3, 2): [B_DUP, B_G],  # B_DUP is deduped away
}


def test_path_b_walks_subcategories_via_the_driver_and_saves_once_per_category(
        repository, fast_sleep, capsys):
    driver = FakeDriver(PATH_B_TOTALS, PATH_B_PAGES)
    session = FakeSession({})  # any GET would fail loudly: Path B is driver-only
    ctx, messages, built = make_ctx(session, repository, category=None,
                                    driver=driver)

    TwoCategoryScraper().run(ctx)

    # The driver visits every subcategory page and every ?page= URL.
    assert driver.urls == [
        base_url("almacen", SUB1),
        page_url("almacen", SUB1, 1),
        page_url("almacen", SUB1, 2),
        base_url("desayuno-y-merienda", SUB3),
        page_url("desayuno-y-merienda", SUB3, 1),
        page_url("desayuno-y-merienda", SUB3, 2),
    ]
    assert driver.scripts == [SCROLL_SCRIPT, SCROLL_SCRIPT]
    # The 10 s waits are requested through the context, not time.sleep.
    assert fast_sleep.requests == [10, 10, 10, 10, 10, 10]
    # The HTTP session is never touched on Path B.
    assert session.urls == []
    # Documents WITH unidad (name_parse applied).
    assert stored_documents(repository) == [
        expected_doc_b("Aceite Girasol", "900 ml", "Girasol", "1001", 1500.5,
                       "almacen"),
        expected_doc_b("Yerba Playadito", "1 kg", "Playadito", "1002", 2500,
                       "almacen"),
        expected_doc_b("Mayonesa Hellmann's", "500 gr", "Hellmann's", "1003",
                       999.99, "almacen"),
        expected_doc_b("Café Mercedolas", "500 gr", "Mercedolas", "1005",
                       1200, "desayuno-y-merienda"),
        expected_doc_b("Alfajor Jorgito", "60 gr", "Jorgito", "1006", 300,
                       "desayuno-y-merienda"),
        expected_doc_b("Mermelada Arcor", "450 gr", "Arcor", "1007", 950,
                       "desayuno-y-merienda"),
    ]
    # One save per category, after its subcategories.
    assert repository.calls == [
        ("Carrefour", "almacen", None, 3),
        ("Carrefour", "desayuno-y-merienda", None, 3),
    ]
    assert driver.quit_count == 1
    assert messages == [
        "Scrapeando categoria: almacen",
        "Inicio Scrap sub-categoria: aceites-y-vinagres",
        "1-49",
        "2-49",
        "Guardados 3 productos de almacen en base de datos",
        "Scrapeando categoria: desayuno-y-merienda",
        "Inicio Scrap sub-categoria: cafe",
        "1-49",
        "2-49",
        "Guardados 3 productos de desayuno-y-merienda en base de datos",
        "PROCESO TERMINADO",
    ]
    assert "Proceso Carrefour terminado" in capsys.readouterr().out


def test_path_b_zero_total_skips_the_subcategory_but_still_saves_the_category(
        repository, fast_sleep):
    driver = FakeDriver({("almacen", SUB_EMPTY): 0, ("almacen", SUB1): 33},
                        {("almacen", SUB1, 1): [B_A]})
    session = FakeSession({})
    ctx, messages, built = make_ctx(session, repository, category=None,
                                    driver=driver)

    EmptyFirstScraper().run(ctx)

    # The empty subcategory was visited and skipped; SUB1 was collected.
    assert driver.urls == [
        base_url("almacen", SUB_EMPTY),
        base_url("almacen", SUB1),
        page_url("almacen", SUB1, 1),
    ]
    assert repository.calls == [("Carrefour", "almacen", None, 1)]
    assert driver.quit_count == 1
    assert built == ["browser"]


def test_path_b_stop_ends_the_page_loop_and_still_saves_the_category(
        repository, fast_sleep):
    stop_event = threading.Event()

    def flip_on_second_page(url):
        if url == page_url("almacen", SUB1, 2):
            stop_event.set()

    # total 65 -> range(1, int(65/16)) == range(1, 4) -> pages 1, 2 and 3.
    driver = FakeDriver({("almacen", SUB1): 65},
                        {("almacen", SUB1, 1): [B_A, B_B],
                         ("almacen", SUB1, 2): [B_C],
                         ("almacen", SUB1, 3): [B_D]},
                        on_get=flip_on_second_page)
    session = FakeSession({})
    ctx, messages, built = make_ctx(session, repository, category=None,
                                    driver=driver, stop_event=stop_event)

    OneSubcategoryScraper().run(ctx)

    # The stop raised during page 2 ended the page loop before page 3.
    assert page_url("almacen", SUB1, 3) not in driver.urls
    assert driver.urls == [
        base_url("almacen", SUB1),
        page_url("almacen", SUB1, 1),
        page_url("almacen", SUB1, 2),
    ]
    # What the category collected is still saved, and the driver is quit.
    assert repository.calls == [("Carrefour", "almacen", None, 3)]
    assert driver.quit_count == 1
    assert built == ["browser"]


def test_path_b_driver_error_is_reported_and_the_run_continues(
        repository, fast_sleep, capsys):
    """The legacy per-subcategory handler (report + print + continue) is
    kept: the broken subcategory is skipped, the rest is still saved."""

    class ExplodingDriver(FakeDriver):
        def get(self, url):
            if url == base_url("almacen", SUB1):
                raise RuntimeError("driver exploded on " + url)
            super().get(url)

    driver = ExplodingDriver({("almacen", SUB2): 33},
                             {("almacen", SUB2, 1): [B_D]})
    session = FakeSession({})
    ctx, messages, built = make_ctx(session, repository, category=None,
                                    driver=driver)

    TwoSubcategoryScraper().run(ctx)

    assert "Error en scraper al traer productos" in messages
    assert "Error en scraper al traer productos" in capsys.readouterr().out
    assert repository.calls == [("Carrefour", "almacen", None, 1)]
    assert driver.quit_count == 1
    assert built == ["browser"]


# -- decision 2: unexpected errors propagate ----------------------------------


def test_path_a_unknown_category_propagates(repository):
    """The manager rejects unknown categories with a 400; if one ever reaches
    the scraper, InvalidCategory propagates instead of the legacy silent
    fall-through that ended the run looking successful."""
    session = FakeSession({})
    ctx, _, built = make_ctx(session, repository, category="plomeria",
                             driver=None)

    with pytest.raises(Exception) as excinfo:
        ScraperCarrefour().run(ctx)
    assert type(excinfo.value).__name__ == "InvalidCategory"
    assert built == []


def test_path_b_broken_browser_propagates_and_still_quits(repository):
    """Decision 2: no outer catch-all was added; a broken driver build lets
    the error escape so the manager marks the run failed."""
    session = FakeSession({})
    ctx, _, _ = make_ctx(session, repository, category=None, driver=None)

    with pytest.raises(AssertionError, match="no browser expected"):
        ScraperCarrefour().run(ctx)


