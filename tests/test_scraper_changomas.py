"""ChangoMás scraper: offline behavior against the VTEX catalog API.

``masonline.com.ar`` is a VTEX store (measured live 2026-11-10): almacén is
4099 products behind ``/api/catalog_system/pub/products/search``, which
answers 400 for ``_from=2501``, and the nine level-2 children of ``almacen``
partition the parent exactly (largest 1544, so no price bisection). The
previous Selenium module drove Chrome against a hardcoded curated cluster and
never read ``/almacen``.

These tests pin that design: tree discovery, the ``resources`` header as the
paging bound, ``productId`` identity, per-subcategory saves, the per-run tree
cache, the cooperative stop, and the absence of a browser. Every run is
machine-faked: no network, no MongoDB, no Chrome.
"""
import json
import threading
from types import SimpleNamespace

import pytest

from api.scrapers.base import ScrapeContext
from api.scrapers.changomas import (SEARCH_URL, TREE_URL, ScraperChangoMas)
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
SUB_A = "aceites-vinagres-y-aderezos"
SUB_B = "snacks"

TREE_JSON = [
    {"id": 1, "name": "Tecnologia",
     "url": "https://www.masonline.com.ar/tecnologia", "children": []},
    {"id": 2, "name": "Almacén",
     "url": "https://www.masonline.com.ar/almacen",
     "children": [
         {"id": 10, "name": "Aceites, Vinagres y Aderezos",
          "url": "https://www.masonline.com.ar/almacen/aceites-vinagres-"
                 "y-aderezos", "children": []},
         {"id": 11, "name": "Snacks",
          "url": "https://www.masonline.com.ar/almacen/snacks",
          "children": [{"id": 12, "name": "Papas fritas",
                        "url": "https://www.masonline.com.ar/almacen/snacks/"
                               "papas-fritas", "children": []}]},
     ]},
]


def vtex_product(name, product_id, price=1000.0, brand="Marca", offer=True,
                 ean="7790272001005"):
    """One product in the shape the VTEX search API returns."""
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
            "categories": ["/Almacén/Aceites, Vinagres y Aderezos/"]}


def expected_doc(name, unidad, brand, sku, price, subcategoria,
                 categoria=ALMACEN, ean="7790272001005"):
    return {"supermercado": "ChangoMas", "name": name, "unidad": unidad,
            "brand": brand, "sku": sku, "price": price, "ean": ean,
            "categoria": categoria, "subcategoria": subcategoria}


def stored_documents(repository):
    return [{key: value for key, value in doc.items()
             if key not in ("_id", "scraped_at")}
            for doc in repository.documents]


def search_url(categoria, subcategoria, start):
    return (f"{SEARCH_URL}/{categoria}/{subcategoria}"
            f"?_from={start}&_to={start + 49}")


def from_of(url):
    """The ``_from`` parameter of a search URL as an int, or None."""
    for parameter in url.split("?", 1)[-1].split("&"):
        key, _, value = parameter.partition("=")
        if key == "_from":
            return int(value)
    return None


def make_ctx(session, repository, *, category=ALMACEN, stop_event=None,
             browser_factory=None):
    messages: list[str] = []
    ctx = ScrapeContext(
        slug=ScraperChangoMas.slug, label=ScraperChangoMas.label,
        category=category, stop_event=stop_event or threading.Event(),
        report=messages.append, repository=repository,
        browser_factory=browser_factory,
        http_factory=lambda: session)
    return ctx, messages


# -- 1. identity and discovery ----------------------------------------------


def test_identity_stays_the_registered_changomas_scraper():
    assert ScraperChangoMas.slug == "changomas"
    assert ScraperChangoMas.label == "ChangoMas"
    assert ScraperChangoMas.categories == ("almacen",)


def test_discovery_reads_the_children_of_almacen_in_tree_order():
    session = FakeSession([FakeResponse(200, TREE_JSON)])
    ctx, _messages = make_ctx(session, InMemoryProductRepository())

    nodes = ScraperChangoMas()._discover_subcategories(ctx, ALMACEN)

    assert [slug for slug, _label, _path in nodes] == [SUB_A, SUB_B]
    assert [label for _slug, label, _path in nodes] == [
        "Aceites, Vinagres y Aderezos", "Snacks"]
    assert [path for _slug, _label, path in nodes] == [
        f"{ALMACEN}/{SUB_A}", f"{ALMACEN}/{SUB_B}"]
    assert session.urls == [TREE_URL]


def test_discovery_never_returns_another_top_category_or_a_grandchild():
    session = FakeSession([FakeResponse(200, TREE_JSON)])
    ctx, _messages = make_ctx(session, InMemoryProductRepository())

    paths = [path for _slug, _label, path
             in ScraperChangoMas()._discover_subcategories(ctx, ALMACEN)]

    assert "tecnologia" not in paths
    assert "almacen/snacks/papas-fritas" not in paths


def test_a_category_missing_from_the_tree_fails_the_discovery():
    """A declared category absent from the tree is fatal (R3-002): returning
    ``[]`` would end the run as a success with zero products, so a renamed
    or removed site path would look healthy."""
    session = FakeSession([FakeResponse(200, TREE_JSON)])
    repository = InMemoryProductRepository()
    ctx, messages = make_ctx(session, repository)
    # -- a missing top-level node: discover directly against a foreign slug
    with pytest.raises(RuntimeError):
        ScraperChangoMas()._discover_subcategories(ctx,
                                                   "bebidas-tres-queen")

    assert repository.calls == []
    assert session.urls == [TREE_URL]
    assert any("bebidas-tres-queen" in message for message in messages)


def test_a_tree_node_without_usable_children_is_skipped_not_fatal(repository):
    """Baseline behaviour, restored: a category that RESOLVES but has no
    usable children is reported and skipped. Only a MISSING category is fatal
    (R3-002); making an empty node fatal would let one legitimately empty
    category block every other one in the same run."""
    tree = json.loads(json.dumps(TREE_JSON))
    for node in tree:
        if node.get("url", "").rstrip("/").endswith("/almacen"):
            node["children"] = []
    session = FakeSession([FakeResponse(200, tree)])
    ctx, messages = make_ctx(session, repository)

    ScraperChangoMas().run(ctx)

    assert repository.calls == []
    assert session.urls == [TREE_URL]
    assert any("Sin subcategorías que recorrer" in message
               for message in messages)
    assert any("PROCESO TERMINADO" in message for message in messages)


# -- 2. happy path ----------------------------------------------------------


def test_full_run_pages_each_subcategory_and_stores_one_slice_each(repository):
    session = FakeSession([
        FakeResponse(200, TREE_JSON),
        FakeResponse(206, [vtex_product("Aceite girasol Cañuelas 900 cc",
                                        "20540", 1899.0, "Cañuelas")],
                     total=1),
        FakeResponse(206, [vtex_product("Papas fritas Cifras 90 g", "555",
                                        2500.0, "Cifras")], total=1),
    ])
    ctx, messages = make_ctx(session, repository)

    ScraperChangoMas().run(ctx)

    assert session.urls == [TREE_URL,
                            search_url(ALMACEN, SUB_A, 0),
                            search_url(ALMACEN, SUB_B, 0)]
    assert repository.calls == [
        ("ChangoMas", ALMACEN, SUB_A, 1),
        ("ChangoMas", ALMACEN, SUB_B, 1),
    ]
    assert stored_documents(repository) == [
        expected_doc("Aceite girasol Cañuelas", "900 cc", "Cañuelas",
                     "20540", 1899.0, SUB_A),
        expected_doc("Papas fritas Cifras", "90 g", "Cifras", "555", 2500.0,
                     SUB_B),
    ]
    assert messages[-1] == "PROCESO TERMINADO"


def test_every_stored_document_carries_the_full_key_set(repository):
    session = FakeSession([
        FakeResponse(200, TREE_JSON),
        FakeResponse(206, [vtex_product("Aceite girasol Cañuelas 900 cc",
                                        "20540", 1899.0)],
                     total=1),
        FakeResponse(206, [], total=0),
    ])
    ctx, _messages = make_ctx(session, repository)

    ScraperChangoMas().run(ctx)

    stored = stored_documents(repository)
    assert len(stored) == 1
    assert set(stored[0]) == {"supermercado", "name", "unidad", "brand",
                              "sku", "price", "ean", "categoria",
                              "subcategoria"}


def test_an_empty_subcategory_is_not_saved(repository):
    session = FakeSession([
        FakeResponse(200, TREE_JSON),
        FakeResponse(206, [], total=0),
        FakeResponse(206, [], total=0),
    ])
    repository = InMemoryProductRepository()
    ctx, _messages = make_ctx(session, repository)

    ScraperChangoMas().run(ctx)

    assert repository.calls == []
    assert repository.documents == []


# -- 3. paging against the offset ceiling ------------------------------------


def test_paging_is_bounded_by_the_resources_header_not_by_the_body():
    """total=120 with one item per page still fetches three pages."""
    session = FakeSession([
        FakeResponse(200, TREE_JSON),
        FakeResponse(206, [vtex_product("A 1 kg", "1")], total=120, start=0),
        FakeResponse(206, [vtex_product("B 1 kg", "2")], total=120, start=50),
        FakeResponse(206, [vtex_product("C 1 kg", "3")], total=120, start=100),
        FakeResponse(206, [vtex_product("D 1 kg", "4")], total=1),
    ])
    ctx, _messages = make_ctx(session, InMemoryProductRepository())

    ScraperChangoMas().run(ctx)

    pages = [url for url in session.urls if "/products/search/" in url]
    assert pages[:3] == [search_url(ALMACEN, SUB_A, 0),
                         search_url(ALMACEN, SUB_A, 50),
                         search_url(ALMACEN, SUB_A, 100)]
    # -- the fourth subcategory holds a single product: no second page
    assert all(from_of(url) != 150 for url in pages if SUB_B in url)


def test_no_page_window_ever_reaches_or_crosses_the_2500_ceiling(repository):
    """Measured live: ``_from=2501`` answers 400. With almacén at 4099 split
    into nine exact children (largest 1544), every walk must finish under the
    ceiling — no page window may reach it, so no price bisection is needed."""
    session = FakeSession([
        FakeResponse(200, TREE_JSON),
        FakeResponse(206, [vtex_product("A 1 kg", "1")], total=60, start=0),
        FakeResponse(206, [vtex_product("A 2 kg", "2")], total=60, start=50),
        FakeResponse(206, [vtex_product("B 1 kg", "3")], total=1),
    ])
    ctx, _messages = make_ctx(session, repository)

    ScraperChangoMas().run(ctx)

    starts = [from_of(url) for url in session.urls
              if from_of(url) is not None]
    assert starts == [0, 50, 0]
    assert all(start < 2500 for start in starts)


def test_dedupe_is_by_product_id_within_a_subcategory(repository):
    repeated = vtex_product("Aceite girasol Cañuelas 900 cc", "20540", 1899.0)
    other = vtex_product("Aceite oliva Familia del Sol 500 cc", "999", 4299.0)

    session = FakeSession([
        FakeResponse(200, TREE_JSON),
        FakeResponse(206, [repeated, repeated, other], total=3),
        FakeResponse(206, [], total=0),
    ])
    ctx, _messages = make_ctx(session, repository)

    ScraperChangoMas().run(ctx)

    assert [doc["sku"] for doc in stored_documents(repository)] == [
        "20540", "999"]


# -- 4. failure modes -------------------------------------------------------


def test_a_tree_network_failure_propagates(repository):
    session = RaisingSession(RuntimeError("network down"))
    ctx, messages = make_ctx(session, repository)

    with pytest.raises(RuntimeError):
        ScraperChangoMas().run(ctx)

    assert repository.calls == []
    assert any("árbol de categorías" in message for message in messages)


def test_a_tree_that_is_not_2xx_fails_the_run_instead_of_succeeding_empty(
        repository):
    """R3-001: a discovery outage must fail the run, not report success with
    zero products while the previous slice stays in the database."""
    session = FakeSession([FakeResponse(500, None)])
    ctx, messages = make_ctx(session, repository)

    with pytest.raises(RuntimeError):
        ScraperChangoMas().run(ctx)

    assert repository.calls == []
    assert any("500" in message for message in messages)


def test_invalid_tree_json_propagates(repository):
    class BrokenJsonResponse:
        status_code = 200
        headers = {}

        def json(self):
            raise ValueError("bad json")

    session = FakeSession([BrokenJsonResponse()])
    ctx, messages = make_ctx(session, repository)

    with pytest.raises(RuntimeError):
        ScraperChangoMas().run(ctx)

    assert repository.calls == []
    assert any("inválido" in message for message in messages)


# -- 5. category validation --------------------------------------------------


def test_validate_category_accepts_almacen():
    assert ScraperChangoMas.validate_category("almacen") == "almacen"


def test_an_unknown_category_is_rejected_before_any_request():
    session = FakeSession([])
    ctx, _messages = make_ctx(session, InMemoryProductRepository(),
                              category="bebidas")

    with pytest.raises(InvalidCategory):
        ScraperChangoMas().run(ctx)

    assert session.urls == []


def test_validate_category_accepts_none():
    assert ScraperChangoMas.validate_category(None) is None


# -- 6. stop, cache and infrastructure seams ---------------------------------


def test_stop_between_pages_halts_the_paging_and_reports_it_stopped(repository):
    stop_event = threading.Event()
    session = FakeSession([
        FakeResponse(200, TREE_JSON),
        FakeResponse(206, [vtex_product("A 1 kg", "1")], total=120, start=0),
    ], stop_event=stop_event, flip_stop_on=1)
    ctx, messages = make_ctx(session, repository, stop_event=stop_event)

    ScraperChangoMas().run(ctx)

    assert search_url(ALMACEN, SUB_A, 50) not in session.urls
    assert messages[-1] == "PROCESO DETENIDO"
    assert "PROCESO TERMINADO" not in messages


def test_the_tree_is_fetched_once_per_run_and_refetched_next_run(repository):
    repository = InMemoryProductRepository()
    first_session = FakeSession([
        FakeResponse(200, TREE_JSON),
        FakeResponse(206, [], total=0),
        FakeResponse(206, [], total=0),
    ])
    ctx, _messages = make_ctx(first_session, repository)
    ScraperChangoMas().run(ctx)
    assert first_session.urls.count(TREE_URL) == 1

    second_session = FakeSession([
        FakeResponse(200, TREE_JSON),
        FakeResponse(206, [], total=0),
        FakeResponse(206, [], total=0),
    ])
    ctx, _messages = make_ctx(second_session, repository)
    ScraperChangoMas().run(ctx)
    assert second_session.urls.count(TREE_URL) == 1


def test_a_pre_cancelled_run_is_inert():
    def forbidden():
        raise AssertionError("no run may build a browser")

    session = FakeSession([])
    ctx, messages = make_ctx(session, InMemoryProductRepository(),
                             stop_event=_set_event(),
                             browser_factory=forbidden)

    ScraperChangoMas().run(ctx)

    assert session.urls == []
    assert messages == []


def test_no_browser_is_ever_built(repository):
    def forbidden():
        raise AssertionError("ChangoMás is scraped through the VTEX API only")

    session = FakeSession([
        FakeResponse(200, TREE_JSON),
        FakeResponse(206, [vtex_product("A 1 kg", "1")], total=1),
        FakeResponse(206, [], total=0),
    ])
    ctx, _messages = make_ctx(session, repository, browser_factory=forbidden)

    ScraperChangoMas().run(ctx)


def test_every_request_is_a_catalog_api_call(repository):
    session = FakeSession([
        FakeResponse(200, TREE_JSON),
        FakeResponse(206, [], total=0),
        FakeResponse(206, [], total=0),
    ])
    ctx, _messages = make_ctx(session, repository)

    ScraperChangoMas().run(ctx)

    assert all("/api/catalog_system/" in url for url in session.urls)
    # -- the hardcoded curated cluster of the Selenium era is gone
    assert not any("productClusterIds" in url or "?map=" in url
                   for url in session.urls)


def _set_event():
    event = threading.Event()
    event.set()
    return event


# -- 6. a page failure is fatal, never a truncated save (R3-001) -------------


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
        ScraperChangoMas().run(ctx)

    assert repository.calls == []
    assert any("No se guarda la recolección parcial" in message
               for message in messages)
    assert not any("PROCESO TERMINADO" in message for message in messages)
