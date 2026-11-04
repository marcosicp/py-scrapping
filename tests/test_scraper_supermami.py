"""SuperMami port (T7): offline fake-HTTP behavior.

Every test runs the ported scraper end to end against canned HTML and an
in-memory repository: exact request order, stored documents, progress
messages and the console output. The legacy-vs-port differential suite that
used to accompany these tests was removed with the legacy module in T14.
"""
import io
import json
import threading
from contextlib import redirect_stdout
from types import SimpleNamespace

from api.scrapers.base import ScrapeContext
from api.scrapers.supermami import ScraperSuperMami

# -- canned HTML -------------------------------------------------------------

RESULT_PAGE = (
    "<html><body>"
    '<p class="txt-result"><strong>1</strong><strong>-</strong>'
    "<strong>72</strong> resultados</p>"
    '<div class="product"></div>'
    "</body></html>"
)


def gtag_page(items):
    """A paginated page whose item list lives in the gtag view_item_list call."""
    payload = json.dumps({"items": items})
    return (
        "<html><body>"
        "<script>gtag('event', 'view_item_list'," + payload + ");</script>"
        "</body></html>"
    )


ITEMS_PAGE_1 = [
    {"name": "Coca Cola 2 lt", "brand": "Coca Cola", "price": 1234.5},
    {"name": "Yerba Playadito 1 kg", "brand": "Playadito", "price": 2500},
]
ITEMS_PAGE_2 = [
    {"name": "Mayonesa Hellmann's 500 gr", "brand": "Hellmann's",
     "price": 999.99},
    {"name": "Aceite Girasol 900 ml", "brand": "Girasol", "price": 1500},
]

# Expected stored shape after name_parse and the name sort.
EXPECTED_DOCUMENTS = [
    {"supermercado": "SuperMami", "name": "Aceite Girasol",
     "unidad": "900 ml", "brand": "Girasol", "price": 1500},
    {"supermercado": "SuperMami", "name": "Coca Cola",
     "unidad": "2 lt", "brand": "Coca Cola", "price": 1234.5},
    {"supermercado": "SuperMami", "name": "Mayonesa Hellmann's",
     "unidad": "500 gr", "brand": "Hellmann's", "price": 999.99},
    {"supermercado": "SuperMami", "name": "Yerba Playadito",
     "unidad": "1 kg", "brand": "Playadito", "price": 2500},
]

# -- the exact URLs the scraper requests --------------------------------------

RESULTS_URL = ('https://www.supermami.com.ar/super/categoria/'
               'supermami-almacen/_/N-1tjm8rd?Nf=product.endDate%7CGTEQ+'
               '1.6723584E12%7C%7Cproduct.startDate%7CLTEQ+1.6723584E12&No=36')
PAGE_URL = ('https://www.supermami.com.ar/super/categoria/'
            'supermami-almacen/_/N-1tjm8rd?Nf=product.endDate%7CGTEQ+'
            '1.6723584E12%7C%7Cproduct.startDate%7CLTEQ+1.6723584E12'
            '&No={offset}&Nr=AND%28product.disponible%3ADisponible%2Cproduct'
            '.language%3Aespa%C3%B1ol%2Cproduct.priceListPair%3A'
            'salePrices_listPrices%2COR%28product.siteId%3AsuperSite%29%29'
            '&Nrpp=36')

FULL_PAGES = [RESULT_PAGE, gtag_page(ITEMS_PAGE_1), gtag_page(ITEMS_PAGE_2)]
# Page 1 (No=0) has items, page 2 (No=36) has none.
EMPTY_MIDDLE_PAGES = [RESULT_PAGE, gtag_page(ITEMS_PAGE_1), gtag_page([])]
# Page 1 (No=0) has none, page 2 has none either.
EMPTY_FIRST_PAGES = [RESULT_PAGE, gtag_page([]), gtag_page([])]
FULL_MESSAGES = [
    "página 1",
    "página 2",
    "Guardados 4 productos de SuperMami en base de datos",
    "PROCESO TERMINADO CON 4 productos",
]


def page_url(offset):
    return PAGE_URL.format(offset=offset)


def stored_documents(repository):
    return [{key: value for key, value in doc.items()
             if key not in ("_id", "scraped_at")}
            for doc in repository.documents]


# -- fakes ------------------------------------------------------------------

def _never_awaited_arender(*args, **kwargs):
    """The legacy calls never await arender; the test reproduces that."""
    return None


class FakeResponse:
    def __init__(self, text):
        self.text = text
        self.html = SimpleNamespace(arender=_never_awaited_arender)


class FakeSession:
    """Offline stand-in for the shared HTTP session; records every GET."""

    def __init__(self, pages, *, stop_event=None, flip_stop_on=None):
        self.urls = []
        self._pages = list(pages)
        self._stop_event = stop_event
        self._flip_stop_on = flip_stop_on

    def get(self, url):
        if (self._stop_event is not None
                and len(self.urls) == self._flip_stop_on):
            self._stop_event.set()
        self.urls.append(url)
        if not self._pages:
            raise AssertionError(f"unexpected extra GET: {url}")
        return FakeResponse(self._pages.pop(0))


def make_ctx(session, repository, *, stop_event=None):
    messages: list[str] = []
    ctx = ScrapeContext(
        slug=ScraperSuperMami.slug, label=ScraperSuperMami.label,
        category=None, stop_event=stop_event or threading.Event(),
        report=messages.append, repository=repository,
        http_factory=lambda: session)
    return ctx, messages


# -- 1. full two-page run -----------------------------------------------------

def test_full_run_requests_the_legacy_urls_and_stores_the_legacy_documents(
        repository, monkeypatch):
    session = FakeSession(FULL_PAGES)
    ctx, messages = make_ctx(session, repository)

    # Nothing in this port touches the filesystem: any open() call fails.
    def forbidden_open(*args, **kwargs):
        raise AssertionError("the ported scraper touched the filesystem")

    monkeypatch.setattr("builtins.open", forbidden_open)

    ScraperSuperMami().run(ctx)

    assert session.urls == [RESULTS_URL, page_url(0), page_url(36)]
    assert stored_documents(repository) == EXPECTED_DOCUMENTS
    assert repository.calls == [("SuperMami", None, None, 4)]
    assert messages == FULL_MESSAGES


def test_full_run_keeps_the_legacy_console_progress(repository):
    """The legacy print lines are part of the mechanical port (D10)."""
    output = io.StringIO()
    with redirect_stdout(output):
        ScraperSuperMami().run(make_ctx(FakeSession(FULL_PAGES),
                                        repository)[0])
    console = output.getvalue()
    assert "Total de paginas SuperMami :72" in console
    assert "scraping data from SuperMami" in console
    assert "scraping data from SuperMami pagina:1" in console
    assert "scraping data from SuperMami pagina:2" in console
    assert "Proceso Mami termino OK, con 4 productos" in console


# -- 1b. the preserved quirk: empty pages do not advance countPages ----------


def test_empty_first_page_repeats_the_offset(repository):
    """Port-only pin of the quirk's most visible case: with page 1 empty,
    both paginated iterations request No=0 (the offset never advanced)."""
    session = FakeSession(EMPTY_FIRST_PAGES)
    ctx, _ = make_ctx(session, repository)
    ScraperSuperMami().run(ctx)
    assert session.urls == [RESULTS_URL, page_url(0), page_url(0)]
    # Nothing collected -> legacy would still delete_many; the port's
    # replace-through-repository is a no-op for an empty result (D6).
    assert repository.calls == []
    assert repository.documents == []


def test_empty_middle_page_runs_like_the_legacy(repository):
    """Focused port test for the audited case: page 1 (No=0) collects items,
    page 2 (No=36) yields zero, so the port fetches exactly the legacy URLs
    and still saves what page 1 collected."""
    session = FakeSession(EMPTY_MIDDLE_PAGES)
    ctx, messages = make_ctx(session, repository)
    ScraperSuperMami().run(ctx)
    assert session.urls == [RESULTS_URL, page_url(0), page_url(36)]
    # Page 2 was parsed but its empty item list collected nothing.
    assert stored_documents(repository) == [EXPECTED_DOCUMENTS[1],
                                            EXPECTED_DOCUMENTS[3]]
    assert repository.calls == [("SuperMami", None, None, 2)]
    assert messages == [
        "página 1",
        "página 2",
        "Guardados 2 productos de SuperMami en base de datos",
        "PROCESO TERMINADO CON 2 productos",
    ]


# -- 2. stop mid-run ----------------------------------------------------------

def test_stop_mid_run_ends_the_run_and_still_saves(repository):
    stop_event = threading.Event()
    session = FakeSession([RESULT_PAGE, gtag_page(ITEMS_PAGE_1)],
                          stop_event=stop_event, flip_stop_on=1)
    ctx, messages = make_ctx(session, repository, stop_event=stop_event)

    ScraperSuperMami().run(ctx)

    # Page 2 was never fetched: the stop was honoured at the top of the loop.
    assert session.urls == [RESULTS_URL, page_url(0)]
    # Page 1 collected: Coca Cola (index 1) and Yerba Playadito (index 3).
    assert stored_documents(repository) == [EXPECTED_DOCUMENTS[1],
                                            EXPECTED_DOCUMENTS[3]]
    assert repository.calls == [("SuperMami", None, None, 2)]
    assert messages == [
        "página 1",
        "Guardados 2 productos de SuperMami en base de datos",
        "PROCESO TERMINADO CON 2 productos",
    ]


