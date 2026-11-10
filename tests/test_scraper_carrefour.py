"""Carrefour scraper: offline behavior against the VTEX catalog API.

Carrefour's `/almacen` is a 4.7 MB VTEX shell with no JSON-LD, so the collector
reads `/api/catalog_system/pub/products/search`, which answers JSON plus a
`resources: from-to/total` header. The offset ceiling is 2500
(`_from=2501` → 400) against 6188 products in almacén, so the run walks the
level-2 categories discovered from `/api/catalog_system/pub/category/tree/2`:
measured live, almacén's ten children partition the parent exactly.

These tests pin that design: tree discovery, the header as the paging bound,
`productId` identity, per-subcategory saves, and the absence of a browser.
"""
import json
import threading
from types import SimpleNamespace

import pytest

from api.scrapers.base import ScrapeContext
from api.scrapers.carrefour import (SEARCH_URL, TREE_URL, ScraperCarrefour)
from api.scrapers.errors import InvalidCategory
from tests.fakes import InMemoryProductRepository

# -- fakes ------------------------------------------------------------------


class FakeResponse:
    """A canned VTEX response: status, decoded JSON and the resources header."""

    def __init__(self, status_code, payload, total=None, start=None):
        self.status_code = status_code
        self._payload = payload
        self.headers = {}
        if total is not None:
            first = 0 if start is None else start
            last = first + len(payload) - 1 if payload else first
            self.headers["resources"] = f"{first}-{last}/{total}"

    def json(self):
        if self._payload is None:
            raise AssertionError("response.json() called on a payload-less "
                                 "response")
        return self._payload


class FakeSession:
    """Returns queued responses in order; an extra GET fails loudly."""

    def __init__(self, responses, *, stop_event=None, flip_stop_on=None):
        self.urls = []
        self._responses = list(responses)
        self._stop_event = stop_event
        self._flip_stop_on = flip_stop_on

    def get(self, url, timeout=None, headers=None):
        if (self._stop_event is not None
                and len(self.urls) == self._flip_stop_on):
            self._stop_event.set()
        self.urls.append(url)
        if not self._responses:
            raise AssertionError(f"unexpected extra GET: {url}")
        return self._responses.pop(0)


class RaisingSession:
    """Session whose every GET fails, like a dead network."""

    def __init__(self, error):
        self.urls = []
        self._error = error

    def get(self, url, timeout=None, headers=None):
        self.urls.append(url)
        raise self._error


@pytest.fixture(autouse=True)
def fast_sleep(monkeypatch):
    """Neutralise the rate-limiting wait: unit tests never sleep."""
    recorder = SimpleNamespace(requests=[])

    def fake_sleep(self, seconds):
        recorder.requests.append(seconds)
        return self.should_stop()

    monkeypatch.setattr(ScrapeContext, "sleep", fake_sleep)
    return recorder


# -- canned VTEX payloads ---------------------------------------------------

ALMACEN = "almacen"
SUB_A = "enlatados-y-conservas"
SUB_B = "snacks"

TREE_JSON = [
    {"id": 1, "name": "Hogar", "url": "https://www.carrefour.com.ar/hogar",
     "children": [{"id": 2, "name": "Bazar",
                   "url": "https://www.carrefour.com.ar/hogar/bazar",
                   "children": []}]},
    {"id": 161, "name": "Almacén", "url": "https://www.carrefour.com.ar/almacen",
     "children": [
         {"id": 162, "name": "Enlatados y Conservas",
          "url": "https://www.carrefour.com.ar/almacen/enlatados-y-conservas",
          "children": []},
         {"id": 163, "name": "Snacks",
          "url": "https://www.carrefour.com.ar/almacen/snacks",
          "children": [{"id": 164, "name": "Papas fritas",
                        "url": "https://www.carrefour.com.ar/almacen/snacks/"
                               "papas-fritas", "children": []}]},
     ]},
]


def vtex_product(name, product_id, price=1000.0, brand="Marca", offer=True,
                 ean="7790272001005"):
    """One product in the shape the VTEX search API returns.

    Every ``items[]`` entry carries an ``ean`` string (live probe, T1);
    ``ean=None`` omits the key.
    """
    item = {"itemId": f"i{product_id}", "name": name}
    if ean is not None:
        item["ean"] = ean
    if offer:
        item["sellers"] = [{"commertialOffer": {"Price": price,
                                                "ListPrice": price}}]
    else:
        item["sellers"] = []
    return {"productName": name, "productId": product_id, "brand": brand,
            "items": [item],
            "categories": ["/Almacén/Enlatados y Conservas/"]}


def expected_doc(name, unidad, brand, sku, price, subcategoria,
                 categoria=ALMACEN, ean="7790272001005"):
    return {"supermercado": "Carrefour", "name": name, "unidad": unidad,
            "brand": brand, "sku": sku, "price": price, "ean": ean,
            "categoria": categoria, "subcategoria": subcategoria}


def stored_documents(repository):
    return [{key: value for key, value in doc.items()
             if key not in ("_id", "scraped_at")}
            for doc in repository.documents]


def search_url(categoria, subcategoria, start):
    return (f"{SEARCH_URL}/{categoria}/{subcategoria}"
            f"?_from={start}&_to={start + 49}")


def make_ctx(session, repository, *, category=ALMACEN, stop_event=None,
             browser_factory=None):
    messages: list[str] = []
    ctx = ScrapeContext(
        slug=ScraperCarrefour.slug, label=ScraperCarrefour.label,
        category=category, stop_event=stop_event or threading.Event(),
        report=messages.append, repository=repository,
        browser_factory=browser_factory,
        http_factory=lambda: session)
    return ctx, messages


# -- 1. identity and discovery ----------------------------------------------


def test_identity_stays_the_registered_carrefour_scraper():
    assert ScraperCarrefour.slug == "carrefour"
    assert ScraperCarrefour.label == "Carrefour"
    assert ScraperCarrefour.categories == ("almacen", "desayuno-y-merienda")


def test_discovery_reads_the_level_two_children_of_the_requested_category():
    session = FakeSession([FakeResponse(200, TREE_JSON)])
    ctx, _messages = make_ctx(session, InMemoryProductRepository())

    nodes = ScraperCarrefour()._discover_subcategories(ctx, ALMACEN)

    assert [slug for slug, _label, _path in nodes] == [SUB_A, SUB_B]
    assert [path for _slug, _label, path in nodes] == [
        "almacen/enlatados-y-conservas", "almacen/snacks"]
    assert session.urls == [TREE_URL]


def test_discovery_never_returns_another_top_category_or_a_grandchild():
    session = FakeSession([FakeResponse(200, TREE_JSON)])
    ctx, _messages = make_ctx(session, InMemoryProductRepository())

    paths = [path for _slug, _label, path
             in ScraperCarrefour()._discover_subcategories(ctx, ALMACEN)]

    assert "hogar/bazar" not in paths
    assert "almacen/snacks/papas-fritas" not in paths


def test_a_category_missing_from_the_tree_fails_the_run(repository):
    """'desayuno-y-merienda' is a registered category but absent from the
    tree: the run must fail instead of ending as a success with zero
    products (R3-002), so a renamed or removed site path cannot look
    healthy."""
    session = FakeSession([FakeResponse(200, TREE_JSON)])
    ctx, messages = make_ctx(session, repository,
                             category="desayuno-y-merienda")

    with pytest.raises(RuntimeError):
        ScraperCarrefour().run(ctx)

    assert repository.calls == []
    assert len(session.urls) == 1
    assert any("desayuno-y-merienda" in message for message in messages)
    assert not any("PROCESO TERMINADO" in message for message in messages)


def test_a_tree_node_without_usable_children_is_skipped_not_fatal(repository):
    """Baseline behaviour, restored: a category that RESOLVES but has no
    usable children is reported and skipped. Making it fatal (only a missing
    category is, R3-002) would let one legitimately empty category block every
    other one in the same run."""
    tree = json.loads(json.dumps(TREE_JSON))
    for node in tree:
        if node.get("url", "").rstrip("/").endswith("/almacen"):
            node["children"] = []
    session = FakeSession([FakeResponse(200, tree)])
    ctx, messages = make_ctx(session, repository, category="almacen")

    ScraperCarrefour().run(ctx)

    assert repository.calls == []
    assert session.urls == [TREE_URL]
    assert any("No se encontraron subcategorías" in message
               for message in messages)
    assert any("PROCESO TERMINADO" in message for message in messages)


# -- 2. happy path ----------------------------------------------------------


def test_full_run_pages_each_subcategory_and_stores_one_slice_each(repository):
    session = FakeSession([
        FakeResponse(200, TREE_JSON),
        FakeResponse(206, [vtex_product("Puré de tomate Arcor 520 g",
                                        "122140", 890.0, "Arcor")],
                     total=1),
        FakeResponse(206, [vtex_product("Papas fritas Lays 90 g", "555",
                                        2500.0, "Lays")], total=1),
    ])
    ctx, messages = make_ctx(session, repository)

    ScraperCarrefour().run(ctx)

    assert session.urls == [TREE_URL,
                            search_url(ALMACEN, SUB_A, 0),
                            search_url(ALMACEN, SUB_B, 0)]
    assert repository.calls == [
        ("Carrefour", ALMACEN, SUB_A, 1),
        ("Carrefour", ALMACEN, SUB_B, 1),
    ]
    assert stored_documents(repository) == [
        expected_doc("Puré de tomate Arcor", "520 g", "Arcor", "122140", 890.0,
                     SUB_A),
        expected_doc("Papas fritas Lays", "90 g", "Lays", "555", 2500.0, SUB_B),
    ]
    assert messages[-1] == "PROCESO TERMINADO"


def test_paging_is_bounded_by_the_resources_header_not_by_the_body():
    """total=120 with two items per page must still fetch three pages."""
    session = FakeSession([
        FakeResponse(200, TREE_JSON),
        FakeResponse(206, [vtex_product("A 1 kg", "1")], total=120, start=0),
        FakeResponse(206, [vtex_product("B 1 kg", "2")], total=120, start=50),
        FakeResponse(206, [vtex_product("C 1 kg", "3")], total=120, start=100),
        FakeResponse(206, [vtex_product("D 1 kg", "4")], total=1, start=0),
    ])
    ctx, _messages = make_ctx(session, InMemoryProductRepository())

    ScraperCarrefour().run(ctx)

    pages = [url for url in session.urls if "/products/search/" in url]
    assert pages[:3] == [search_url(ALMACEN, SUB_A, 0),
                         search_url(ALMACEN, SUB_A, 50),
                         search_url(ALMACEN, SUB_A, 100)]
    assert search_url(ALMACEN, SUB_A, 150) not in pages


def test_an_empty_subcategory_is_not_saved(repository):
    session = FakeSession([
        FakeResponse(200, TREE_JSON),
        FakeResponse(206, [], total=0),
        FakeResponse(206, [], total=0),
    ])
    ctx, _messages = make_ctx(session, repository)

    ScraperCarrefour().run(ctx)

    assert repository.calls == []
    assert repository.documents == []


# -- 3. field mapping -------------------------------------------------------


def test_price_comes_from_the_offer_and_a_missing_offer_stores_zero():
    session = FakeSession([
        FakeResponse(200, TREE_JSON),
        FakeResponse(206, [vtex_product("Sin oferta 500 gr", "900",
                                        offer=False),
                           vtex_product("Con oferta 500 gr", "901", 1800.5)],
                     total=2),
        FakeResponse(206, [], total=0),
    ])
    repository = InMemoryProductRepository()
    ctx, _messages = make_ctx(session, repository)

    ScraperCarrefour().run(ctx)

    stored = stored_documents(repository)
    assert [(doc["name"], doc["price"], doc["sku"]) for doc in stored] == [
        ("Sin oferta", 0, "900"),
        ("Con oferta", 1800.5, "901"),
    ]


def test_dedupe_is_by_product_id_within_a_subcategory():
    repeated = vtex_product("Puré de tomate Arcor 520 g", "122140", 890.0)
    other = vtex_product("Puré de tomate Carrefour 520 g", "999", 929.0)
    session = FakeSession([
        FakeResponse(200, TREE_JSON),
        FakeResponse(206, [repeated, repeated, other], total=3),
        FakeResponse(206, [], total=0),
    ])
    repository = InMemoryProductRepository()
    ctx, _messages = make_ctx(session, repository)

    ScraperCarrefour().run(ctx)

    assert [doc["sku"] for doc in stored_documents(repository)] == [
        "122140", "999"]


def test_ean_comes_from_the_item_and_a_missing_ean_stores_empty():
    """The live probe verified every ``items[]`` entry carries an ``ean``
    string; an item without the key must not crash the run and stores
    ``""``."""
    session = FakeSession([
        FakeResponse(200, TREE_JSON),
        FakeResponse(206, [vtex_product("Con EAN 500 gr", "801", 1200.5,
                                        ean="7794567890123"),
                           vtex_product("Sin EAN 500 gr", "802", 1200.5,
                                        ean=None)],
                     total=2),
        FakeResponse(206, [], total=0),
    ])
    repository = InMemoryProductRepository()
    ctx, _messages = make_ctx(session, repository)

    ScraperCarrefour().run(ctx)

    stored = stored_documents(repository)
    assert [(doc["sku"], doc["ean"]) for doc in stored] == [
        ("801", "7794567890123"),
        ("802", ""),
    ]


# -- 4. failure modes -------------------------------------------------------


class _FailsAfterFirstPage:
    """The tree, then one page, then a dead network."""

    def __init__(self, first_page, error):
        self.urls = []
        self._first_page = first_page
        self._error = error

    def get(self, url, timeout=None, headers=None):
        self.urls.append(url)
        if len(self.urls) == 1:
            return FakeResponse(200, TREE_JSON)
        if len(self.urls) == 2:
            return self._first_page
        raise self._error


def _network_failure_session():
    return _FailsAfterFirstPage(
        FakeResponse(206, [vtex_product("A 1 kg", "1")], total=120),
        RuntimeError("network down"))


def _server_error_session():
    return FakeSession([
        FakeResponse(200, TREE_JSON),
        FakeResponse(206, [vtex_product("A 1 kg", "1")], total=120),
        FakeResponse(500, None),
    ])


def _invalid_json_session():
    return FakeSession([
        FakeResponse(200, TREE_JSON),
        FakeResponse(206, [vtex_product("A 1 kg", "1")], total=120),
        FakeResponse(200, None),
    ])


@pytest.mark.parametrize("build_session", [
    _network_failure_session,
    _server_error_session,
    _invalid_json_session,
])
def test_a_page_failure_never_saves_a_truncated_slice(build_session):
    """R3-001: ``replace_products`` REPLACES the slice, so saving the
    documents collected before a page failure would wipe the stored catalog
    for this subcategory while the run still reported ``PROCESO TERMINADO``.
    The failure has to fail the run instead."""
    repository = InMemoryProductRepository()
    ctx, messages = make_ctx(build_session(), repository)

    with pytest.raises(Exception):
        ScraperCarrefour().run(ctx)

    assert repository.calls == []
    assert any("No se guarda la recolección parcial" in message
               for message in messages)
    assert not any("PROCESO TERMINADO" in message for message in messages)


def test_a_tree_that_is_not_2xx_fails_the_run_instead_of_succeeding_empty(
        repository):
    """R3-001: a discovery outage must fail the run, not report success with
    zero products while the previous slice stays in the database."""
    session = FakeSession([FakeResponse(500, None)])
    ctx, messages = make_ctx(session, repository)

    with pytest.raises(RuntimeError):
        ScraperCarrefour().run(ctx)

    assert repository.calls == []
    assert any("500" in message for message in messages)


def test_a_tree_network_failure_fails_the_run(repository):
    session = RaisingSession(RuntimeError("network down"))
    ctx, _messages = make_ctx(session, repository)

    with pytest.raises(RuntimeError):
        ScraperCarrefour().run(ctx)

    assert repository.calls == []


# -- 5. stop and infrastructure seams --------------------------------------


def test_stop_between_pages_halts_the_paging_and_reports_it_stopped(repository):
    stop_event = threading.Event()
    session = FakeSession([
        FakeResponse(200, TREE_JSON),
        FakeResponse(206, [vtex_product("A 1 kg", "1")], total=120, start=0),
    ], stop_event=stop_event, flip_stop_on=1)
    ctx, messages = make_ctx(session, repository, stop_event=stop_event)

    ScraperCarrefour().run(ctx)

    assert search_url(ALMACEN, SUB_A, 50) not in session.urls
    assert messages[-1] == "PROCESO DETENIDO"
    assert "PROCESO TERMINADO" not in messages


def test_a_pre_cancelled_run_is_inert():
    def forbidden():
        raise AssertionError("no run may build a browser")

    session = FakeSession([])
    ctx, messages = make_ctx(session, InMemoryProductRepository(),
                             stop_event=_set_event(),
                             browser_factory=forbidden)

    ScraperCarrefour().run(ctx)

    assert session.urls == []
    assert messages == []


def test_no_browser_is_ever_built(repository):
    def forbidden():
        raise AssertionError("Carrefour is scraped through the VTEX API only")

    session = FakeSession([
        FakeResponse(200, TREE_JSON),
        FakeResponse(206, [vtex_product("A 1 kg", "1")], total=1),
        FakeResponse(206, [], total=0),
    ])
    ctx, _messages = make_ctx(session, repository, browser_factory=forbidden)

    ScraperCarrefour().run(ctx)


def test_no_html_page_is_ever_requested(repository):
    session = FakeSession([
        FakeResponse(200, TREE_JSON),
        FakeResponse(206, [], total=0),
        FakeResponse(206, [], total=0),
    ])
    ctx, _messages = make_ctx(session, repository)

    ScraperCarrefour().run(ctx)

    assert all("/api/catalog_system/" in url for url in session.urls)
    assert not any(url.rstrip("/").endswith("/almacen") for url in session.urls)


def test_the_rate_limit_is_one_second_per_page(repository, fast_sleep):
    session = FakeSession([
        FakeResponse(200, TREE_JSON),
        FakeResponse(206, [vtex_product("A 1 kg", "1")], total=120, start=0),
        FakeResponse(206, [vtex_product("B 1 kg", "2")], total=120, start=50),
        FakeResponse(206, [vtex_product("C 1 kg", "3")], total=120, start=100),
        FakeResponse(206, [], total=0),
    ])
    ctx, _messages = make_ctx(session, repository)

    ScraperCarrefour().run(ctx)

    assert fast_sleep.requests == [1, 1]


def test_an_unknown_category_is_rejected_before_any_request():
    session = FakeSession([])
    ctx, _messages = make_ctx(session, InMemoryProductRepository(),
                              category="hogar")

    with pytest.raises(InvalidCategory):
        ScraperCarrefour().run(ctx)

    assert session.urls == []


def test_without_a_category_every_registered_category_is_walked(repository):
    tree = json.loads(json.dumps(TREE_JSON))
    tree.append({"id": 300, "name": "Desayuno y merienda",
                 "url": "https://www.carrefour.com.ar/desayuno-y-merienda",
                 "children": [{"id": 301, "name": "Yerba",
                               "url": "https://www.carrefour.com.ar/"
                                      "desayuno-y-merienda/yerba",
                               "children": []}]})
    session = FakeSession([
        FakeResponse(200, tree),
        FakeResponse(206, [vtex_product("A 1 kg", "1")], total=1),
        FakeResponse(206, [vtex_product("B 1 kg", "2")], total=1),
        FakeResponse(206, [vtex_product("C 1 kg", "3")], total=1),
        FakeResponse(206, [vtex_product("D 1 kg", "4")], total=1),
    ])
    ctx, _messages = make_ctx(session, repository, category=None)

    ScraperCarrefour().run(ctx)

    assert [subcategoria for _sm, _cat, subcategoria, _n in repository.calls] == [
        SUB_A, SUB_B, "yerba"]
    assert [categoria for _sm, categoria, _sub, _n in repository.calls] == [
        ALMACEN, ALMACEN, "desayuno-y-merienda"]


def _set_event():
    event = threading.Event()
    event.set()
    return event
