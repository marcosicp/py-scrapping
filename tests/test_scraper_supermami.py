"""SuperMami scraper: offline behavior against Oracle Endeca.

``/super/home`` resolves each category's Endeca path at run time; every
``?No=<offset>&Nrpp=500`` page carries the products in the embedded
``gtag('event', 'view_item_list', {...})`` script and the category total in
``Resultado ... de <strong>N</strong>``, with no offset ceiling (measured on
2026-11-05: ``No=3200`` still answers a full window). The parent category is
the collection scope: the 15 level-2 children ``almacen`` sum 2 680 while
the parent reports 3 210, so descending would silently lose 530 products.
The parent is paged whole, deduped by ``item_id`` across every page, guarded
by the stop-aware 3-attempt retry policy the Disco run established, and an
incomplete walk is always reported with the exact missing count. Identity is
``item_id``, stored as ``sku`` (the legacy stored none and capped the walk
at 2 hardcoded pages).

The tests pin that design fully offline: a fake HTTP session whose canned
menu and Endeca pages are exactly like the measured ones (each window sliced
from an ordered item pool and reporting the pool's size as the total), an
in-memory repository, and no network, no browser, no database and no real
sleep anywhere.
"""
import io
import json
import threading
from contextlib import redirect_stdout
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from api.scrapers.base import ScrapeContext
from api.scrapers.errors import InvalidCategory
from api.scrapers.supermami import (BASE_URL, MENU_URL, PAGE_SIZE,
                                    PAGE_SLEEP_SECONDS, TIMEOUT,
                                    ScraperSuperMami)
from tests.fakes import InMemoryProductRepository

ALMACEN = "almacen"
PATH = "/super/categoria/supermami-almacen/_/N-1tjm8rd"

# -- canned data ---------------------------------------------------------------

# The measured menu (2026-11-05): the parent category has NO href at all —
# its category path lives only inside an anchor's ``onclick``
# ``getPageCategory('/super/categoria/supermami-almacen/_/N-1tjm8rd', ...)` —
# while 263 anchors carry a ``supermami-almacen`` href and every one of them
# is a child or grandchild (e.g. ``supermami-almacen-aceites-vinagres-...``),
# coming first in document order.
CHILD_HREF_1 = ("/super/categoria/supermami-almacen-aceites-vinagres-y-acetos"
                "-aceites/_/N-5j2xvv")
CHILD_HREF_2 = ("/super/categoria/supermami-almacen-aceites-vinagres-y-acetos"
                "-acetos-especiales/_/N-7j2xxv")
CHILD_HREF_3 = ("/super/categoria/supermami-almacen-golosinas-y-chocolates"
                "/_/N-6j2xww")
PARENT_ONCLICK = ("javascript:getPageCategory('/super/categoria/"
                  "supermami-almacen/_/N-1tjm8rd', '', event);")
BEBIDAS_HREF = "/super/categoria/supermami-bebidas/_/N-2tjm8re"


def _anchors(links):
    """The measured anchor shapes: children with ``href``, the parent with
    only an ``onclick``."""
    rendered = []
    for link in links:
        text = link["text"]
        href = link.get("href")
        onclick = link.get("onclick")
        if href is not None:
            rendered.append(f"<li><a href='{href}'>{text}</a></li>")
        else:
            # The live page double-quotes ``onclick`` because its value
            # itself contains single quotes.
            rendered.append(f'<li><a onclick="{onclick}">{text}</a></li>')
    return "".join(rendered)


def child(name, href):
    return {"href": href, "text": name}


def parent(name, onclick):
    return {"onclick": onclick, "text": name}


MENU_HTML = (
    "<html><body><ul class='menu'>"
    # Children first, exactly as measured in document order:
    + _anchors([child("Aceites", CHILD_HREF_1),
                child("Especiales", CHILD_HREF_2),
                child("Golosinas", CHILD_HREF_3)])
    # ... then the parent, only inside its ``onclick``:
    + _anchors([parent("Almacén", PARENT_ONCLICK)])
    + _anchors([child("Bebidas", BEBIDAS_HREF)])
    + "</ul></body></html>"
)


def menu_without(categoria):
    """A 200 menu that answers but simply does not list the category."""
    return MENU_HTML.replace(f"supermami-{categoria}", "supermami-nope")


def menus_no_parent():
    """The parent is absent; only ``almacen``-prefixed children exist."""
    return ("<html><body><ul class='menu'>"
            + _anchors([child("Aceites", CHILD_HREF_1),
                        child("Especiales", CHILD_HREF_2),
                        child("Golosinas", CHILD_HREF_3),
                        child("Bebidas", BEBIDAS_HREF)])
            + "</ul></body></html>")


def item(item_id, name, *, brand="Marca", category="Azúcar", price=None):
    """One ``view_item_list`` entry, in the measured payload shape."""
    entry = {"item_id": item_id, "item_name": name,
             "item_brand": brand, "item_category": category}
    if price is not None:
        entry["price"] = price
    return entry


def filler(index):
    """A synthetic product whose name carries no unit: the stored document
    keeps the name verbatim, an empty ``unidad`` and the given price."""
    return item(f"prod{4000 + index}", f"Producto test {index}",
                brand="Marca", category="Almacén general", price=float(index))


def page_html(items, *, total=3210, last=None, before=""):
    """One category page: the Endeca total line and the gtag script.

    ``before`` lets a test position extra HTML before the total line, to
    pin that foreign ``de <strong>N</strong>`` never binds the total.
    """
    payload = json.dumps({"items": items})
    last = last if last is not None else len(items)
    return (
        "<html><head></head><body>"
        f"{before}"
        '<p class="txt-result">Resultado <strong>1</strong> a '
        f"<strong>{last}</strong> de <strong>{total}</strong></p>"
        "<script>window.dataLayer = window.dataLayer || [];</script>"
        f"<script>gtag('event', 'view_item_list', {payload});</script>"
        "</body></html>"
    )


def windows(catalog):
    """The Endeca pages of an ordered item pool: the window at ``No=start``
    serves ``pool[start:start + PAGE_SIZE]`` and reports the pool's size as
    the category total — the measured behavior, scaled down to test data."""
    pages = {}
    for start in range(0, len(catalog), PAGE_SIZE):
        chunk = catalog[start:start + PAGE_SIZE]
        pages[start] = page_html(chunk, total=len(catalog),
                                 last=start + len(chunk))
    return pages


# -- fakes -------------------------------------------------------------------


class FakeResponse:
    def __init__(self, text, status_code=200):
        self.status_code = status_code
        self.text = text


class FakeSession:
    """Offline stand-in for the shared HTTP session; records every GET.

    The menu URL is canned on its own; ``pages`` maps a ``No=`` offset to
    the canned page. ``failures`` is a consumed-per-match list of
    ``(url substring, outcome)`` where an outcome is an exception (a network
    error), an int status code, or a list of those (one element per match,
    like the transient 500s the Disco tests model).
    """

    def __init__(self, menu, pages, *, failures=(), stop_event=None,
                 flip_stop_on=None):
        self.urls = []
        self.timeouts = []
        self._menu = menu
        self._pages = pages
        self._failures = list(failures)
        self._stop_event = stop_event
        self._flip_stop_on = flip_stop_on

    def get(self, url, timeout=None):
        self.urls.append(url)
        self.timeouts.append(timeout)
        if (self._stop_event is not None
                and len(self.urls) == self._flip_stop_on):
            self._stop_event.set()
        for index, (needle, outcome) in enumerate(self._failures):
            if needle not in url:
                continue
            if isinstance(outcome, list):
                fired = outcome.pop(0)
                if not outcome:
                    del self._failures[index]
            else:
                fired = outcome
                del self._failures[index]
            if isinstance(fired, BaseException):
                raise fired
            return FakeResponse(f"error {fired}", status_code=int(fired))
        if url == MENU_URL:
            return FakeResponse(self._menu)
        query = parse_qs(urlsplit(url).query)
        start = int((query.get("No") or ["0"])[0])
        if start not in self._pages:
            raise AssertionError(f"unexpected GET: {url}")
        return FakeResponse(self._pages[start])


@pytest.fixture(autouse=True)
def fast_sleep(monkeypatch):
    """Neutralise the wait: unit tests never sleep."""
    recorder = SimpleNamespace(requests=[])

    def fake_sleep(self, seconds):
        recorder.requests.append(seconds)
        return self.should_stop()

    monkeypatch.setattr(ScrapeContext, "sleep", fake_sleep)
    return recorder


def page_url(start, path=PATH):
    """The exact Endeca page request: the offset stepped by ``Nrpp``."""
    return f"{BASE_URL}{path}?No={start}&Nrpp={PAGE_SIZE}"


def stored_documents(repository):
    return [{key: value for key, value in doc.items()
             if key not in ("_id", "scraped_at")}
            for doc in repository.documents]


def expected_doc(name, unidad, brand, sku, price, subcategoria):
    return {"supermercado": "SuperMami", "name": name, "unidad": unidad,
            "brand": brand, "sku": sku, "price": price,
            "categoria": ALMACEN, "subcategoria": subcategoria}


def expected_filler(index):
    return expected_doc(f"Producto test {index}", "", "Marca",
                        f"prod{4000 + index}", float(index),
                        "Almacén general")


def make_ctx(session, repository, *, category=None, stop_event=None):
    messages: list[str] = []
    ctx = ScrapeContext(
        slug=ScraperSuperMami.slug, label=ScraperSuperMami.label,
        category=category, stop_event=stop_event or threading.Event(),
        report=messages.append, repository=repository,
        http_factory=lambda: session)
    return ctx, messages


def non_backoff_sleeps(fast_sleep):
    return [seconds for seconds in fast_sleep.requests
            if seconds != PAGE_SLEEP_SECONDS]


# -- 1. the happy path: the whole category in three windows --------------------

PAGE_TOTAL = 1200

COCA = item("prod1001", "Coca Cola 2 lt", brand="Coca-Cola",
            category="Gaseosas", price=1234.5)
YERBA = item("prod1002", "Yerba Playadito 1 kg", brand="Playadito",
             category="Yerbas", price=2500)
MAYO = item("prod1003", "Mayonesa Hellmann's 500 gr", brand="Hellmann's",
            category="Mayonesas", price=999.99)
SAL = item("prod1004", "Sal Mina 500 gr", brand="Sal Mina",
           category="Sal")  # no ``price`` key: stored as 0
ACEITE = item("prod1005", "Aceite Girasol 900 ml", brand="Girasol",
              category="Aceites", price=1500)

HAPPY_POOL = ([COCA, YERBA, MAYO, SAL]
              + [filler(index) for index in range(1, 1197)])

HAPPY_DOCUMENTS = [
    expected_doc("Coca Cola", "2 lt", "Coca-Cola", "prod1001", 1234.5,
                 "Gaseosas"),
    expected_doc("Yerba Playadito", "1 kg", "Playadito", "prod1002", 2500,
                 "Yerbas"),
    expected_doc("Mayonesa Hellmann's", "500 gr", "Hellmann's", "prod1003",
                 999.99, "Mayonesas"),
    expected_doc("Sal Mina", "500 gr", "Sal Mina", "prod1004", 0, "Sal"),
] + [expected_filler(index) for index in range(1, 1197)]

# The slice is stored name-sorted (the baseline order), so the awaited
# documents of a full run are the pool's documents in name order.
HAPPY_DOCUMENTS.sort(key=lambda doc: doc["name"])


def test_identity_stays_the_registered_supermami_scraper():
    assert ScraperSuperMami.slug == "supermami"
    assert ScraperSuperMami.label == "SuperMami"
    assert ScraperSuperMami.categories == (ALMACEN,)


def test_full_run_pages_the_whole_category_and_saves_once(repository,
                                                          fast_sleep):
    session = FakeSession(MENU_HTML, windows(HAPPY_POOL))
    repository = InMemoryProductRepository()
    ctx, messages = make_ctx(session, repository)

    ScraperSuperMami().run(ctx)

    assert session.urls == [MENU_URL, page_url(0), page_url(500),
                            page_url(1000)]
    assert all(timeout == TIMEOUT for timeout in session.timeouts)
    assert repository.calls == [("SuperMami", ALMACEN, None, PAGE_TOTAL)]
    assert stored_documents(repository) == HAPPY_DOCUMENTS
    assert messages == [
        "Scrapeando categoria: almacen",
        "Total de productos en almacen: 1200",
        "página 1/3",
        "página 2/3",
        "página 3/3",
        "Guardados 1200 productos de almacen en base de datos",
        "PROCESO TERMINADO",
    ]
    assert non_backoff_sleeps(fast_sleep) == []  # only the page pacing


def test_the_run_uses_no_console_output(repository):
    session = FakeSession(MENU_HTML, windows(HAPPY_POOL))
    out = io.StringIO()
    with redirect_stdout(out):
        ScraperSuperMami().run(make_ctx(session, repository)[0])
    assert out.getvalue() == ""


# -- 2. menu discovery --------------------------------------------------------


def test_the_category_path_comes_from_the_menu_not_the_code(repository):
    """The run resolves ``supermami-almacen`` from ``/super/home`` — here
    with an id no code could have hardcoded — and pages that path."""
    menu = MENU_HTML.replace("N-1tjm8rd", "N-zz9zz9z")
    session = FakeSession(menu, {0: page_html([], total=0)})
    ctx, messages = make_ctx(session, repository)

    ScraperSuperMami().run(ctx)

    assert session.urls == [
        MENU_URL,
        page_url(0, path="/super/categoria/supermami-almacen/_/N-zz9zz9z")]
    assert repository.calls == []
    assert messages[-1] == "PROCESO TERMINADO"


def test_the_resolved_path_is_paged_with_the_menu_endeca_id(repository):
    menu = MENU_HTML.replace("N-1tjm8rd", "N-zz9zz9z")
    session = FakeSession(menu, {0: page_html([], total=0)})
    repository = InMemoryProductRepository()
    ctx, _ = make_ctx(session, repository)
    ScraperSuperMami().run(ctx)
    # The Endeca id came from the menu, nowhere in the code.
    assert f"{BASE_URL}/super/categoria/supermami-almacen/_/N-zz9zz9z" \
        in " ".join(session.urls)


def test_documents_are_saved_name_sorted_as_the_baseline_did(repository):
    """The baseline sorted the slice by stored name before saving; the walk
    appends in Endeca page order, and the slice must come out sorted."""
    unordered = [
        item("prodA_z", "Zapallo Corriente 1 kg", brand="Verduleria",
             category="Verduras", price=900.0),
        item("prodA_m", "Manzana Roja Popular 1 kg", brand="Roma",
             category="Frutas", price=1200.0),
        item("prodA_a", "Aceite Girasol 900 ml", brand="Girasol",
             category="Aceites", price=1500.0),
    ]
    session = FakeSession(MENU_HTML, windows(unordered))
    repository = InMemoryProductRepository()
    ctx, _ = make_ctx(session, repository)

    ScraperSuperMami().run(ctx)

    names = [doc["name"] for doc in stored_documents(repository)]
    assert names == ["Aceite Girasol", "Manzana Roja Popular",
                     "Zapallo Corriente"]


def test_a_numeric_string_price_is_parsed(repository):
    payload = item("prodA_v", "Harina Blanca fina 1 kg", brand="Blanca",
                   category="Harinas", price="499.99")
    session = FakeSession(MENU_HTML,
                          {0: page_html([payload], total=1)})
    ctx, _ = make_ctx(session, repository)

    ScraperSuperMami().run(ctx)

    assert stored_documents(repository) == [
        expected_doc("Harina Blanca fina", "1 kg", "Blanca", "prodA_v",
                     499.99, "Harinas")]


def test_the_menu_is_refetched_per_run_and_cached_only_within_it(repository):
    scraper = ScraperSuperMami()
    session = FakeSession(MENU_HTML, windows(HAPPY_POOL))
    repository = InMemoryProductRepository()
    scraper.run(make_ctx(session, repository)[0])
    scraper.run(make_ctx(session, repository)[0])
    assert session.urls.count(MENU_URL) == 2


def test_a_declared_category_missing_from_the_menu_fails(repository):
    """``categories`` is a contract: a valid menu that no longer lists the
    declared category means the scraper is broken — the run must fail
    loudly instead of ending as a success with a stale saved slice
    (R3-002)."""
    session = FakeSession(menu_without(ALMACEN), {})
    ctx, messages = make_ctx(session, repository)

    with pytest.raises(RuntimeError):
        ScraperSuperMami().run(ctx)

    assert session.urls == [MENU_URL]
    assert repository.calls == []
    assert any("No se encontró la categoría almacen" in message
               for message in messages)
    # Superseded by R3-002: a declared category missing from a valid menu
    # is fatal, never a silent skip.
    assert "PROCESO TERMINADO" not in messages


def test_a_menu_with_links_but_no_category_paths_is_an_outage(repository):
    """A 200 body with links but no ``/super/categoria/…`` path anywhere
    (bot wall, error page) is not a menu: reported and raised — never a
    search through links that silently reads as 'category missing'
    (R3-002)."""
    menu = ("<html><body>"
            "<a href='/carrito'>Carrito</a>"
            "<a href='/ayuda'>Ayuda</a>"
            "</body></html>")
    session = FakeSession(menu, {})
    ctx, messages = make_ctx(session, repository)

    with pytest.raises(RuntimeError):
        ScraperSuperMami().run(ctx)

    assert session.urls == [MENU_URL]
    assert repository.calls == []
    assert any("Menú inválido" in message for message in messages)


def test_a_menu_network_error_is_reported_and_fatal(repository):
    session = FakeSession(MENU_HTML, {},
                          failures=[("/super/home",
                                     ConnectionError("closed"))])
    ctx, messages = make_ctx(session, repository)

    with pytest.raises(ConnectionError):
        ScraperSuperMami().run(ctx)

    assert session.urls == [MENU_URL]
    assert repository.calls == []
    assert any("Error de red al leer el menú" in message
               for message in messages)


def test_a_menu_status_error_is_reported_and_fatal(repository):
    session = FakeSession(MENU_HTML, {}, failures=[("/super/home", 503)])
    ctx, messages = make_ctx(session, repository)

    with pytest.raises(RuntimeError):
        ScraperSuperMami().run(ctx)

    assert session.urls == [MENU_URL]
    assert repository.calls == []
    assert any("Error 503 al leer el menú" in message
               for message in messages)


def test_children_before_the_parent_still_resolve_the_parent(repository):
    """Measured live: every ``supermami-almacen`` href is a child or a
    grandchild and comes first in document order, while the parent appears
    only inside an ``onclick``. The run must resolve the parent's path and
    page the parent's total — never the first child (75 products), which
    the substring test would have picked."""
    session = FakeSession(MENU_HTML, windows(HAPPY_POOL))
    repository = InMemoryProductRepository()
    ctx, messages = make_ctx(session, repository)

    ScraperSuperMami().run(ctx)

    assert session.urls == [MENU_URL, page_url(0), page_url(500),
                            page_url(1000)]
    assert any("Total de productos en almacen: 1200" in message
               for message in messages)
    assert messages[-1] == "PROCESO TERMINADO"


def test_a_child_similar_slug_never_resolves_the_category(repository):
    """A menu whose ``almacen``-prefixed links are all children of the
    ``supermami-almacen-<algo>`` form, with the parent absent, must NOT
    resolve a child — and, per the declared `categories` contract, the
    declared category being absent from a valid menu is fatal."""
    menu = menus_no_parent()
    session = FakeSession(menu, {})
    ctx, messages = make_ctx(session, repository)

    with pytest.raises(RuntimeError):
        ScraperSuperMami().run(ctx)

    assert session.urls == [MENU_URL]
    assert repository.calls == []
    assert any("No se encontró la categoría almacen" in message
               for message in messages)
    assert "PROCESO TERMINADO" not in messages


def test_the_parent_wins_regardless_of_document_order(repository):
    """Children both before and after the parent anchor: the exact segment
    match picks the parent from ``onclick`` either way."""
    menu = ("<html><body><ul class='menu'>"
            + _anchors([child("Aceites", CHILD_HREF_1),
                        parent("Almacén", PARENT_ONCLICK),
                        child("Golosinas", CHILD_HREF_3)])
            + "</ul></body></html>")
    session = FakeSession(menu, windows(HAPPY_POOL))
    repository = InMemoryProductRepository()
    ctx, _ = make_ctx(session, repository)

    ScraperSuperMami().run(ctx)

    assert session.urls[0] == MENU_URL
    assert session.urls[1] == page_url(0)


def test_invalid_menu_html_is_reported_and_fatal(repository):
    """A 200 body with no category links at all is not a menu: fatal."""
    session = FakeSession("<html><body>Acceso denegado</body></html>", {})
    ctx, messages = make_ctx(session, repository)

    with pytest.raises(RuntimeError):
        ScraperSuperMami().run(ctx)

    assert session.urls == [MENU_URL]
    assert repository.calls == []
    assert any("Menú inválido" in message for message in messages)


# -- 3. the paging bound, dedupe and the document shape ------------------------

def test_a_decoy_de_strong_before_the_resultado_never_binds_the_total(
        repository):
    """Measured live: today's page happens to have exactly two
    ``de <strong>N</strong>`` matches, both 3210 — but the total regex
    matched any of them. A decoy ``verde <strong>3</strong>`` before the
    real ``Resultado`` line must never bind a total of 3 that would stop
    the walk after one window and keep the gap guard silent."""
    pages = windows([filler(i) for i in range(701)])
    pages[0] = ("<html><body><p>Hoja verde <strong>3</strong> del catálogo"
                "</p></body></html>" + pages[0].replace("<html><body>", ""))
    session = FakeSession(MENU_HTML, pages)
    repository = InMemoryProductRepository()
    ctx, messages = make_ctx(session, repository)

    ScraperSuperMami().run(ctx)

    assert session.urls == [MENU_URL, page_url(0), page_url(500)]
    assert any("Total de productos en almacen: 701" in message
               for message in messages)
    assert not any("faltantes" in message for message in messages)
    assert messages[-1] == "PROCESO TERMINADO"


def test_a_page_without_the_resultado_sentence_reports_and_fails(repository,
                                                                 fast_sleep):
    """A page whose gtag payload parses but carries no ``Resultado … de``
    sentence gives no paging bound: 'Respuesta sin total' and raise."""
    broken = (page_html([COCA], total=701, last=701)
              .replace('<p class="txt-result">Resultado <strong>1</strong> a '
                       "<strong>701</strong> de <strong>701</strong></p>", ""))
    session = FakeSession(MENU_HTML, {0: broken})
    ctx, messages = make_ctx(session, repository)

    with pytest.raises(RuntimeError):
        ScraperSuperMami().run(ctx)

    assert session.urls == [MENU_URL, page_url(0)]
    assert repository.calls == []
    assert any("Respuesta sin total" in message for message in messages)


def test_the_reported_total_bounds_the_paging(repository):
    """A pool of exactly 1000 at ``Nrpp=500`` means two windows: no request
    at or beyond the reported total is ever made."""
    session = FakeSession(MENU_HTML, windows([filler(i) for i in range(1000)]))
    ctx, _ = make_ctx(session, repository)

    ScraperSuperMami().run(ctx)

    assert session.urls == [MENU_URL, page_url(0), page_url(500)]


def test_an_empty_window_inside_the_total_ends_the_walk(repository):
    """A 200 page with a valid but empty ``view_item_list`` list stops the
    paging — its gap against the reported total is never silent."""
    pages = {0: page_html([COCA], total=1000, last=500),
             500: page_html([], total=1000, last=500)}
    session = FakeSession(MENU_HTML, pages)
    repository = InMemoryProductRepository()
    ctx, messages = make_ctx(session, repository)

    ScraperSuperMami().run(ctx)

    assert session.urls == [MENU_URL, page_url(0), page_url(500)]
    assert repository.calls == [("SuperMami", ALMACEN, None, 1)]
    assert any("999 productos faltantes" in message
               for message in messages)
    assert messages[-1] == "PROCESO TERMINADO"


def test_a_pool_larger_than_page_size_pages_beyond_the_first_window(
        repository):
    """701 products: the second window fetches from ``No=500`` on."""
    session = FakeSession(MENU_HTML, windows([filler(i) for i in range(701)]))
    repository = InMemoryProductRepository()
    ctx, _ = make_ctx(session, repository)

    ScraperSuperMami().run(ctx)

    assert session.urls == [MENU_URL, page_url(0), page_url(500)]
    assert repository.calls == [("SuperMami", ALMACEN, None, 701)]


def test_dedupes_by_item_id_across_pages(repository):
    """Endeca may reprint a product between windows: the second occurrence
    never becomes a second document (D-5), and the first one stands."""
    reprint = item("prod1001", "Coca Cola 3 lt", brand="Coca-Cola",
                   category="Gaseosas", price=1234.5)
    duplicated = ([COCA] + [filler(i) for i in range(1, 500)]
                  + [reprint, ACEITE]
                  + [filler(i) for i in range(500, 1198)])
    assert len(duplicated) == 1200
    session = FakeSession(MENU_HTML, windows(duplicated))
    repository = InMemoryProductRepository()
    ctx, _ = make_ctx(session, repository)

    ScraperSuperMami().run(ctx)

    stored = stored_documents(repository)
    assert len(stored) == 1199
    names = [doc["name"] for doc in stored]
    assert names == sorted(names)  # the baseline order
    assert [doc["sku"] for doc in stored].count("prod1001") == 1
    assert expected_doc("Coca Cola", "2 lt", "Coca-Cola", "prod1001",
                        1234.5, "Gaseosas") in stored


def test_a_genuinely_non_numeric_price_is_stored_as_zero(repository):
    stale = item("prod1009", "Harina Blanca 1 kg", brand="Blanca",
                 category="Harinas", price="abc")
    missing = item("prod1010", "Arroz Grano fino 1 kg", brand="Dos Hermanos",
                   category="Arroces")
    session = FakeSession(MENU_HTML,
                          {0: page_html([stale, missing], total=2, last=2)})
    ctx, _ = make_ctx(session, repository)

    ScraperSuperMami().run(ctx)

    stored = stored_documents(repository)
    assert [doc["price"] for doc in stored] == [0, 0]


# -- 4. the page-error retry policy --------------------------------------------


def test_a_page_without_gtag_payload_fails_after_the_retries(repository,
                                                             fast_sleep):
    """A 200 page with no ``view_item_list`` object is a page error: three
    attempts with 2 s / 4 s backoff, then reported and raised (D-7)."""
    pages = {0: "<html><body><p>La página está vacía</p></body></html>"}
    session = FakeSession(MENU_HTML, pages)
    ctx, messages = make_ctx(session, repository)

    with pytest.raises(RuntimeError):
        ScraperSuperMami().run(ctx)

    assert session.urls == [MENU_URL] + [page_url(0)] * 3
    assert non_backoff_sleeps(fast_sleep) == [2, 4]
    assert repository.calls == []
    assert any("Respuesta sin datos" in message for message in messages)


def test_an_unparsable_gtag_payload_fails_after_the_retries(repository,
                                                            fast_sleep):
    pages = {
        0: "<script>gtag('event', 'view_item_list', "
           "{\"items\": [ not json at all );</script>"}
    session = FakeSession(MENU_HTML, pages)
    ctx, messages = make_ctx(session, repository)

    with pytest.raises(RuntimeError):
        ScraperSuperMami().run(ctx)

    assert session.urls == [MENU_URL] + [page_url(0)] * 3
    assert non_backoff_sleeps(fast_sleep) == [2, 4]
    assert repository.calls == []
    assert any("Respuesta sin datos" in message for message in messages)


def test_a_transient_500_is_retried_once_and_the_page_succeeds(repository,
                                                               fast_sleep):
    session = FakeSession(MENU_HTML, windows(HAPPY_POOL),
                          failures=[("No=0", 500)])
    repository = InMemoryProductRepository()
    ctx, messages = make_ctx(session, repository)

    ScraperSuperMami().run(ctx)

    assert session.urls.count(page_url(0)) == 2
    assert non_backoff_sleeps(fast_sleep) == [2]
    assert repository.calls == [("SuperMami", ALMACEN, None, PAGE_TOTAL)]
    assert messages[-1] == "PROCESO TERMINADO"


def test_three_500s_exhaust_the_retries_and_fail_the_run(repository,
                                                         fast_sleep):
    session = FakeSession(MENU_HTML, windows(HAPPY_POOL),
                          failures=[("No=0", [500, 500, 500])])
    repository = InMemoryProductRepository()
    ctx, messages = make_ctx(session, repository)

    with pytest.raises(RuntimeError):
        ScraperSuperMami().run(ctx)

    assert session.urls == [MENU_URL] + [page_url(0)] * 3
    assert non_backoff_sleeps(fast_sleep) == [2, 4]
    assert repository.calls == []
    assert any("Error 500" in message for message in messages)


def test_a_4xx_fails_on_the_first_attempt_without_any_retry(repository,
                                                            fast_sleep):
    """A 4xx means the request is wrong, not the server: one request only,
    no backoff sleep, and the run fails (the Disco policy)."""
    session = FakeSession(MENU_HTML, windows(HAPPY_POOL),
                          failures=[("No=0", 400)])
    repository = InMemoryProductRepository()
    ctx, messages = make_ctx(session, repository)

    with pytest.raises(RuntimeError):
        ScraperSuperMami().run(ctx)

    assert session.urls == [MENU_URL, page_url(0)]
    assert fast_sleep.requests == []
    assert repository.calls == []
    assert any("Error 400" in message for message in messages)


def test_a_transient_network_error_is_retried_and_succeeds(repository,
                                                           fast_sleep):
    session = FakeSession(MENU_HTML, windows(HAPPY_POOL),
                          failures=[("No=0",
                                     ConnectionError("timed out"))])
    repository = InMemoryProductRepository()
    ctx, _ = make_ctx(session, repository)

    ScraperSuperMami().run(ctx)

    assert session.urls.count(page_url(0)) == 2
    assert non_backoff_sleeps(fast_sleep) == [2]
    assert repository.calls == [("SuperMami", ALMACEN, None, PAGE_TOTAL)]


def test_a_stop_during_backoff_ends_the_run_as_stopped(repository,
                                                       fast_sleep):
    """Window 0 was collected; window 500's first attempt answers 500 and
    the stop fires during its backoff: the run ends PROCESO DETENIDO with
    what was collected saved, and the walk's gap is still reported."""
    stop_event = threading.Event()
    session = FakeSession(MENU_HTML, windows([filler(i) for i in range(1500)]),
                          failures=[("No=500", 500)],
                          stop_event=stop_event, flip_stop_on=3)
    repository = InMemoryProductRepository()
    ctx, messages = make_ctx(session, repository, stop_event=stop_event)

    ScraperSuperMami().run(ctx)

    assert session.urls == [MENU_URL, page_url(0), page_url(500)]
    assert repository.calls == [("SuperMami", ALMACEN, None, 500)]
    assert 2 in fast_sleep.requests
    assert any("1000 productos faltantes" in message
               for message in messages)
    assert messages[-1] == "PROCESO DETENIDO"
    assert "PROCESO TERMINADO" not in messages


# -- 5. stop -------------------------------------------------------------------


def test_stop_during_paging_saves_the_partial_documents_and_reports_the_gap(
        repository):
    stop_event = threading.Event()
    session = FakeSession(MENU_HTML, windows([filler(i) for i in range(1500)]),
                          stop_event=stop_event, flip_stop_on=3)
    repository = InMemoryProductRepository()
    ctx, messages = make_ctx(session, repository, stop_event=stop_event)

    ScraperSuperMami().run(ctx)

    assert session.urls == [MENU_URL, page_url(0), page_url(500)]
    assert repository.calls == [("SuperMami", ALMACEN, None, 1000)]
    expected = [expected_filler(index) for index in range(1000)]
    expected.sort(key=lambda doc: doc["name"])
    assert stored_documents(repository) == expected
    assert any("500 productos faltantes" in message
               for message in messages)
    assert messages[-1] == "PROCESO DETENIDO"
    assert "PROCESO TERMINADO" not in messages


def test_a_pre_cancelled_run_touches_nothing(repository):
    stop_event = threading.Event()
    stop_event.set()
    session = FakeSession(MENU_HTML, {})
    ctx, messages = make_ctx(session, repository, stop_event=stop_event)

    ScraperSuperMami().run(ctx)

    assert session.urls == []
    assert messages == []
    assert repository.calls == []


# -- 6. category validation ------------------------------------------------------


def test_an_invalid_category_is_rejected(repository):
    session = FakeSession(MENU_HTML, {})
    ctx, _ = make_ctx(session, repository, category="bebidas")

    with pytest.raises(InvalidCategory):
        ScraperSuperMami().run(ctx)

    assert session.urls == []
    assert repository.calls == []
