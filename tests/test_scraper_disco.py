"""Disco scraper: offline behavior against the VTEX catalog API.

`/almacen`'s HTML needs a browser; the catalog API does not. The tree at
``/api/catalog_system/pub/category/tree/2`` and the search endpoint
``/api/catalog_system/pub/products/search/<path>`` (206 with a
``resources: from-to/total`` header, measured on 2026-11-05) answer everything
the HTML path scraped. The offset ceiling is 2550 items (``_from=2500&_to=2550``
→ 400), and nodes bigger than that are read through inclusive
``fq=P:[lo TO hi]`` price buckets bisected until each one fits, so the
duplicates on a bucket boundary are collapsed by the ``productId`` dedupe.

These tests pin that design offline: the fake session answers the two
endpoints the way the measured API does, and nothing here ever opens a
browser, touches an HTML page or the network.
"""
import re
import threading
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

import api.scrapers.disco as disco_module
from api.scrapers.base import ScrapeContext
from api.scrapers.disco import (SEARCH_URL, TREE_URL, ScraperDisco)
from api.scrapers.errors import InvalidCategory
from tests.fakes import InMemoryProductRepository

# -- canned data -------------------------------------------------------------

ALMACEN = "almacen"
SUB = "aceites-y-vinagres"
SUB2 = "golosinas-y-chocolates"

BASE = "https://www.disco.com.ar"

TREE_JSON = [
    {"id": 5, "name": "Tecnología",
     "url": f"{BASE}/tecnologia", "children": []},
    {"id": 100, "name": "Almacén",
     "url": f"{BASE}/almacen", "children": [
         {"id": 101, "name": "Aceites y Vinagres",
          "url": f"{BASE}/almacen/{SUB}", "children": []},
         {"id": 102, "name": "Golosinas y Chocolates",
          "url": f"{BASE}/almacen/{SUB2}", "children": [
              # A level-3 grandchild: discovery must stop at level 2.
              {"id": 103, "name": "Galletitas",
               "url": f"{BASE}/almacen/{SUB2}/galletitas", "children": []},
          ]},
     ]},
]


def product(name, product_id, price=1000.0, brand="Marca", offer=True):
    """One product in the shape the VTEX search API returns."""
    item = {"itemId": f"i{product_id}", "name": name}
    if offer:
        item["sellers"] = [{"commertialOffer": {"Price": price,
                                                "ListPrice": price}}]
    else:
        item["sellers"] = []
    return {"productName": name, "productId": product_id, "brand": brand,
            "items": [item],
            "categories": ["/Almacén/Aceites y Vinagres/"]}


def node_catalog(spec):
    """``[(price, product), ...]`` per ``(price, count)`` pairs, unique ids."""
    entries = []
    product_id = 0
    for price, count in spec:
        for _ in range(count):
            product_id += 1
            entries.append((price,
                            product(f"Producto test {product_id}", product_id,
                                    price)))
    return entries


# -- fakes -------------------------------------------------------------------


class FakeResponse:
    """A canned VTEX response: status, decoded JSON and the resources header."""

    def __init__(self, status_code, payload=None, *, total=None, first=0,
                 last=0, valid_json=True, text=""):
        self.status_code = status_code
        self._payload = payload
        self._valid_json = valid_json
        self.text = text
        self.headers = {}
        if total is not None:
            self.headers["resources"] = f"{first}-{last}/{total}"

    def json(self):
        if not self._valid_json:
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        if self._payload is None:
            raise AssertionError("response.json() called on a payload-less "
                                 "response")
        return self._payload


PRICE_RANGE = re.compile(r"P:\[([^\s\]]+)\s+TO\s+([^\]]+)\]")


class VtexSession:
    """Offline stand-in for the measured catalog API.

    ``catalog`` maps a node path (``/almacen/aceites-y-vinagres``) to the
    ordered ``(price, product)`` list the search endpoint pages there.
    ``failures`` is a consumed-on-first-match list of ``(url substring,
    outcome)`` where an outcome is a raising exception, a response status,
    or ``"invalid-json"``.

    Faithful to the measured API: any window with ``_to > 2549`` or
    ``_from >= 2501`` answers 400 (the offset ceiling), and an empty result
    answers 200 with ``resources: 0-0/0`` and body ``[]`` — never 206.
    """

    def __init__(self, tree, catalog, *, failures=(),
                 stop_event=None, flip_stop_on=None):
        self.urls = []
        self.timeouts = []
        self.tree = tree
        self.catalog = catalog
        self._failures = list(failures)
        self._stop_event = stop_event
        self._flip_stop_on = flip_stop_on

    def get(self, url, timeout=None, headers=None):
        self.urls.append(url)
        self.timeouts.append(timeout)
        if (self._stop_event is not None
                and len(self.urls) == self._flip_stop_on):
            self._stop_event.set()
        for index, (pattern, outcome) in enumerate(self._failures):
            if pattern in url:
                del self._failures[index]
                if isinstance(outcome, BaseException):
                    raise outcome
                if outcome == "invalid-json":
                    return FakeResponse(200, valid_json=False)
                return FakeResponse(int(outcome), text=f"error {outcome}")

        parts = urlsplit(url)
        if parts.path.rstrip("/") == "/api/catalog_system/pub/category/tree/2":
            return FakeResponse(200, self.tree)

        query = parse_qs(parts.query)
        start = int((query.get("_from") or ["0"])[0])
        end = int((query.get("_to") or [str(start)])[0])
        order = (query.get("O") or [None])[0]
        price_range = PRICE_RANGE.match((query.get("fq") or [""])[0])
        node = parts.path[len("/api/catalog_system/pub/products/search"):]
        entries = self.catalog.get(node, [])
        if price_range:
            lo, hi = float(price_range.group(1)), float(price_range.group(2))
            entries = [entry for entry in entries if lo <= entry[0] <= hi]
        if order == "OrderByPriceASC":
            items = [product for _price, product
                     in sorted(entries, key=lambda entry: entry[0])[:1]]
            if not items:
                return FakeResponse(200, [], total=0, first=start, last=end)
            return FakeResponse(206, items, total=len(entries),
                                first=start, last=end)
        if order == "OrderByPriceDESC":
            items = [product for _price, product
                     in sorted(entries, key=lambda entry: entry[0])[-1:]]
            if not items:
                return FakeResponse(200, [], total=0, first=start, last=end)
            return FakeResponse(206, items, total=len(entries),
                                first=start, last=end)
        total = len(entries)
        if not total:
            # Verified live: an empty result is 200 with resources 0-0/0,
            # never a 206 — a zero-total bucket is skipped, not fatal.
            return FakeResponse(200, [], total=0, first=start, last=end)
        if end > 2549 or start >= 2501:
            # Verified live: `_from=2500&_to=2549` is the last valid window;
            # `_to=2550` and `_from=2501` both answer 400.
            return FakeResponse(400, text="the offset window is capped")
        items = [product for _price, product
                 in entries[start:min(end, total - 1) + 1]]
        return FakeResponse(206, items, total=total, first=start, last=end)


@pytest.fixture(autouse=True)
def fast_sleep(monkeypatch):
    """Neutralise the rate-limiting wait: unit tests never sleep."""
    recorder = SimpleNamespace(requests=[])

    def fake_sleep(self, seconds):
        recorder.requests.append(seconds)
        return self.should_stop()

    monkeypatch.setattr(ScrapeContext, "sleep", fake_sleep)
    return recorder


def stored_documents(repository):
    return [{key: value for key, value in doc.items()
             if key not in ("_id", "scraped_at")}
            for doc in repository.documents]


def expected_doc(name, unidad, brand, sku, price, subcategoria):
    return {"supermercado": "Disco", "name": name, "unidad": unidad,
            "brand": brand, "sku": sku, "price": price,
            "categoria": ALMACEN, "subcategoria": subcategoria}


def probe_url(node, price_range=None, order=None):
    query = "_from=0&_to=0"
    if order:
        query = f"{query}&O={order}"
    if price_range:
        query = f"{query}&fq=P:[{price_range[0]} TO {price_range[1]}]"
    return f"{SEARCH_URL}{node}?{query}"


def window_url(node, start, price_range=None):
    query = f"_from={start}&_to={start + 49}"
    if price_range:
        query = f"{query}&fq=P:[{price_range[0]} TO {price_range[1]}]"
    return f"{SEARCH_URL}{node}?{query}"


def make_ctx(session, repository, *, category=ALMACEN, stop_event=None,
             browser_factory=None):
    messages: list[str] = []
    ctx = ScrapeContext(
        slug=ScraperDisco.slug, label=ScraperDisco.label,
        category=category, stop_event=stop_event or threading.Event(),
        report=messages.append, repository=repository,
        browser_factory=browser_factory,
        http_factory=lambda: session)
    return ctx, messages


# -- 1. identity and discovery ----------------------------------------------


def test_identity_stays_the_registered_disco_scraper():
    assert ScraperDisco.slug == "disco"
    assert ScraperDisco.label == "Disco"
    assert ScraperDisco.categories == (ALMACEN,)


def test_discovery_reads_the_level_two_children_of_the_requested_category():
    session = VtexSession(TREE_JSON, {})
    ctx, _messages = make_ctx(session, InMemoryProductRepository())

    children = ScraperDisco()._discover_subcategories(ctx, ALMACEN)

    assert session.urls == [TREE_URL]
    assert [slug for slug, _label, _path in children] == [SUB, SUB2]
    assert [label for _slug, label, _path in children] == [
        "Aceites y Vinagres", "Golosinas y Chocolates"]
    assert [path for _slug, _label, path in children] == [
        f"{ALMACEN}/{SUB}", f"{ALMACEN}/{SUB2}"]


def test_discovery_never_returns_another_top_category_or_a_grandchild():
    session = VtexSession(TREE_JSON, {})
    ctx, _messages = make_ctx(session, InMemoryProductRepository())

    paths = [path for _slug, _label, path
             in ScraperDisco()._discover_subcategories(ctx, ALMACEN)]

    assert paths == [f"{ALMACEN}/{SUB}", f"{ALMACEN}/{SUB2}"]


def test_a_category_missing_from_the_tree_says_so_and_the_run_continues():
    """'almacen' is a registered category but absent from the measured tree:
    reported, nothing requested or saved, and the run still ends cleanly."""
    tree = [dict(TREE_JSON[0])]  # only 'tecnología', no 'almacén' node
    session = VtexSession(tree, {})
    repository = InMemoryProductRepository()
    ctx, messages = make_ctx(session, repository, category=ALMACEN)

    ScraperDisco().run(ctx)

    assert session.urls == [TREE_URL]
    assert repository.calls == []
    assert any("No se encontraron subcategorías" in message
               for message in messages)
    assert messages[-1] == "PROCESO TERMINADO"


def test_the_tree_is_refetched_per_run_and_only_then_cached():
    """One tree GET per run (an instance attribute set at run start), not a
    class-level cache shared between runs."""
    session = VtexSession(TREE_JSON, {})
    repository = InMemoryProductRepository()
    scraper = ScraperDisco()

    scraper.run(make_ctx(session, repository)[0])
    scraper.run(make_ctx(session, repository)[0])
    assert session.urls.count(TREE_URL) == 2

    # Inside the same run the cache holds: a second discovery asks nothing.
    ctx, _messages = make_ctx(session, repository)
    scraper._discover_subcategories(ctx, ALMACEN)
    assert session.urls.count(TREE_URL) == 2


# -- 2. happy path -----------------------------------------------------------


def test_full_run_pages_each_node_and_stores_one_slice_per_child(repository):
    def forbidden():
        raise AssertionError("Disco is scraped through the VTEX API only")

    bulk = [(400.0 + index, product(f"Diverso test {index} 500 gr", index,
                                    400.0 + index))
            for index in range(1, 70)]
    catalog = {
        f"/{ALMACEN}/{SUB}": [(890.0, product("Puré de tomate Arcor 520 g",
                                              122140, 890.0, "Arcor"))] + bulk,
        f"/{ALMACEN}/{SUB2}": [],
    }
    session = VtexSession(TREE_JSON, catalog)
    ctx, messages = make_ctx(session, repository, browser_factory=forbidden)

    ScraperDisco().run(ctx)

    assert session.urls == [
        TREE_URL,
        probe_url(f"/{ALMACEN}/{SUB}"),
        window_url(f"/{ALMACEN}/{SUB}", 0),
        window_url(f"/{ALMACEN}/{SUB}", 50),
        probe_url(f"/{ALMACEN}/{SUB2}"),
    ]
    assert session.timeouts == [30, 90, 90, 90, 90]
    assert repository.calls == [("Disco", ALMACEN, SUB, 70)]
    stored = stored_documents(repository)
    assert stored[0] == expected_doc("Puré de tomate Arcor", "520 g", "Arcor",
                                     "122140", 890.0, SUB)
    # The paged range is bounded by the resources header (70): at start=100
    # the loop stops, no `_from=100` is ever requested.
    assert window_url(f"/{ALMACEN}/{SUB}", 100) not in session.urls
    assert messages[-1] == "PROCESO TERMINADO"
    assert not any("faltan" in message for message in messages)


def test_a_zero_total_node_probes_once_and_saves_nothing(repository):
    node = f"/{ALMACEN}/{SUB}"
    node2 = f"/{ALMACEN}/{SUB2}"
    session = VtexSession(TREE_JSON, {node: [], node2: []})
    repository = InMemoryProductRepository()
    ctx, _messages = make_ctx(session, repository)

    ScraperDisco().run(ctx)

    assert session.urls == [TREE_URL, probe_url(node), probe_url(node2)]
    assert repository.calls == []
    assert repository.documents == []


def test_dedupe_is_by_product_id_within_a_node(repository):
    node = f"/{ALMACEN}/{SUB}"
    repeated = (1000.0, product("Puré de tomate Arcor 500 gr", 1, 1000.0))
    catalog = {node: [repeated, repeated,
                      (1000.0, product("Puré de tomate Disco 500 gr", 2,
                                       1000.0))]}
    session = VtexSession(TREE_JSON, catalog)
    repository = InMemoryProductRepository()
    ctx, _messages = make_ctx(session, repository)

    ScraperDisco().run(ctx)

    assert [doc["sku"] for doc in stored_documents(repository)] == ["1", "2"]


# -- 3. the 2550 ceiling and the price partition -----------------------------


def test_an_oversized_node_is_bisected_by_price_and_every_bucket_is_paged(
        repository):
    """total 2700 > MAX_WINDOW: bounds probes, bisection probes, then the
    buckets in detection order. The 100 products priced exactly on the split
    boundary fall in both buckets and are stored exactly once."""
    node = f"/{ALMACEN}/{SUB}"
    catalog = {node: node_catalog([(1.0, 1300), (6.0, 100), (11.0, 1300)]),
               f"/{ALMACEN}/{SUB2}": []}
    session = VtexSession(TREE_JSON, catalog)
    repository = InMemoryProductRepository()
    ctx, messages = make_ctx(session, repository)

    ScraperDisco().run(ctx)

    assert session.urls[:7] == [
        TREE_URL,
        probe_url(node),
        probe_url(node, order="OrderByPriceASC"),
        probe_url(node, order="OrderByPriceDESC"),
        probe_url(node, price_range=(1.0, 11.0)),
        probe_url(node, price_range=(1.0, 6.0)),
        probe_url(node, price_range=(6.0, 11.0)),
    ]
    buckets = session.urls[7:]
    first_bucket = [window_url(node, start, price_range=(1.0, 6.0))
                    for start in range(0, 1400, 50)]
    second_bucket = [window_url(node, start, price_range=(6.0, 11.0))
                     for start in range(0, 1400, 50)]
    assert buckets == first_bucket + second_bucket \
        + [probe_url(f"/{ALMACEN}/{SUB2}")]
    assert repository.calls == [("Disco", ALMACEN, SUB, 2700)]
    skus = [doc["sku"] for doc in stored_documents(repository)]
    assert skus.count("1301") == 1  # a boundary product, stored once
    assert len(skus) == len(set(skus)) == 2700
    assert not any("faltan" in message for message in messages)


def test_bisection_that_cannot_split_reports_the_exact_unreachable_count(
        repository):
    """All 3000 products share one price: the bucket cannot split, the
    reachable window (items 0..2549) is still collected and the 450 missing
    are reported by name."""
    node = f"/{ALMACEN}/{SUB}"
    catalog = {node: node_catalog([(100.0, 3000)]), f"/{ALMACEN}/{SUB2}": []}
    session = VtexSession(TREE_JSON, catalog)
    repository = InMemoryProductRepository()
    ctx, messages = make_ctx(session, repository)

    ScraperDisco().run(ctx)

    assert session.urls[:5] == [
        TREE_URL,
        probe_url(node),
        probe_url(node, order="OrderByPriceASC"),
        probe_url(node, order="OrderByPriceDESC"),
        probe_url(node, price_range=(100.0, 100.0)),
    ]
    bucket = session.urls[5:-1]
    assert bucket == [window_url(node, start, price_range=(100.0, 100.0))
                      for start in range(0, 2550, 50)]
    assert session.urls[-1] == probe_url(f"/{ALMACEN}/{SUB2}")
    # The ceiling is never crossed: the last window ends at index 2549.
    assert "_to=2550" not in "".join(session.urls)
    assert repository.calls == [("Disco", ALMACEN, SUB, 2550)]
    skus = [doc["sku"] for doc in stored_documents(repository)]
    assert len(skus) == len(set(skus)) == 2550
    assert any("450" in message for message in messages)


def test_a_bumped_max_window_hits_the_live_ceiling_and_fails_the_run(
        repository, monkeypatch):
    """The fake enforces the measured API ceiling, so the scraper cannot
    regress without the suite catching it: bump MAX_WINDOW past 2550 and the
    window at 2550+ answers 400, which fails the run loudly."""
    node = f"/{ALMACEN}/{SUB}"
    session = VtexSession(TREE_JSON, {node: node_catalog([(100.0, 3000)]),
                                      f"/{ALMACEN}/{SUB2}": []})
    repository = InMemoryProductRepository()
    ctx, messages = make_ctx(session, repository)
    monkeypatch.setattr(disco_module, "MAX_WINDOW", 10 ** 6)

    with pytest.raises(RuntimeError):
        ScraperDisco().run(ctx)

    # The last legal window (2500..2549) was served; the very next window
    # crossed the ceiling and the fake answered 400.
    assert window_url(node, 2500) in session.urls
    assert window_url(node, 2550) in session.urls
    assert any("Error 400" in message for message in messages)
    assert repository.calls == []


def test_an_empty_price_bucket_is_skipped_and_the_other_buckets_are_paged(
        repository):
    """A distribution gap inside the measured range (no product between 8.5
    and 11.0): the empty bucket probe answers 200 with `0-0/0`, is skipped
    without failing, the 100 products of [6.0 TO 8.5] are fully paged, and
    the single-price remainder converges to a ceiling-capped bucket."""
    node = f"/{ALMACEN}/{SUB}"
    catalog = {node: node_catalog([(6.0, 100), (11.0, 2900)]),
               f"/{ALMACEN}/{SUB2}": []}
    session = VtexSession(TREE_JSON, catalog)
    repository = InMemoryProductRepository()
    ctx, messages = make_ctx(session, repository)

    ScraperDisco().run(ctx)

    assert probe_url(node, price_range=(8.5, 9.75)) in session.urls
    assert window_url(node, 0, price_range=(6.0, 8.5)) in session.urls
    assert window_url(node, 50, price_range=(6.0, 8.5)) in session.urls
    skus = [doc["sku"] for doc in stored_documents(repository)]
    assert len(skus) == len(set(skus)) == 100 + 2550
    assert any("350" in message for message in messages)
    assert messages[-1] == "PROCESO TERMINADO"


# -- 4. failure modes --------------------------------------------------------


@pytest.mark.parametrize("outcome", [
    RuntimeError("network down"),
    503,
    "invalid-json",
])
def test_a_tree_outage_is_fatal_and_never_looks_like_no_subcategories(
        repository, outcome):
    """R3-001: a discovery outage must fail the run, not end as a success
    with zero products while the previous slice stays in the database."""
    session = VtexSession(TREE_JSON, {}, failures=[("category/tree", outcome)])
    repository = InMemoryProductRepository()
    ctx, messages = make_ctx(session, repository)

    with pytest.raises(RuntimeError):
        ScraperDisco().run(ctx)

    assert repository.calls == []
    assert not any("No se encontraron subcategorías" in message
                   for message in messages)
    assert any("rbol de categor" in message for message in messages)


@pytest.mark.parametrize("outcome", [RuntimeError("network down"), 500])
def test_a_product_window_error_is_reported_and_propagates(repository,
                                                           outcome):
    """No retries: a failed window fails the child and the run (D-9)."""
    node = f"/{ALMACEN}/{SUB}"
    session = VtexSession(TREE_JSON, {node: node_catalog([(10.0, 70)])},
                          failures=[("_to=49", outcome)])
    repository = InMemoryProductRepository()
    ctx, messages = make_ctx(session, repository)

    with pytest.raises(RuntimeError):
        ScraperDisco().run(ctx)

    assert session.urls[:3] == [TREE_URL, probe_url(node),
                                window_url(node, 0)]
    assert window_url(node, 50) not in session.urls
    assert repository.calls == []
    if isinstance(outcome, int):
        assert any("500" in message for message in messages)
    else:
        assert any("Error de red" in message for message in messages)


# -- 5. stop -----------------------------------------------------------------


def test_stop_during_paging_saves_the_partial_documents_and_reports_it(
        repository):
    stop_event = threading.Event()
    node = f"/{ALMACEN}/{SUB}"
    session = VtexSession(TREE_JSON, {node: node_catalog([(10.0, 120)])},
                          stop_event=stop_event, flip_stop_on=3)
    repository = InMemoryProductRepository()
    ctx, messages = make_ctx(session, repository, stop_event=stop_event)

    ScraperDisco().run(ctx)

    assert window_url(node, 0) in session.urls
    assert window_url(node, 50) not in session.urls
    assert repository.calls == [("Disco", ALMACEN, SUB, 50)]
    assert messages[-1] == "PROCESO DETENIDO"
    assert "PROCESO TERMINADO" not in messages


def test_a_pre_cancelled_run_is_inert():
    def forbidden():
        raise AssertionError("no run may build a browser")

    session = VtexSession(TREE_JSON, {})
    ctx, messages = make_ctx(session, InMemoryProductRepository(),
                             stop_event=_set_event(), browser_factory=forbidden)

    ScraperDisco().run(ctx)

    assert session.urls == []
    assert messages == []


# -- 6. field mapping and validation -----------------------------------------


def test_price_comes_from_the_offer_and_a_missing_offer_stores_zero(repository):
    node = f"/{ALMACEN}/{SUB}"
    catalog = {node: [(0.0, product("Sin oferta 500 gr", 900, offer=False)),
                      (1800.5, product("Con oferta 500 gr", 901, 1800.5))]}
    session = VtexSession(TREE_JSON, catalog)
    repository = InMemoryProductRepository()
    ctx, _messages = make_ctx(session, repository)

    ScraperDisco().run(ctx)

    stored = stored_documents(repository)
    assert [(doc["name"], doc["price"], doc["sku"]) for doc in stored] == [
        ("Sin oferta", 0, "900"),
        ("Con oferta", 1800.5, "901"),
    ]


def test_an_unknown_category_is_rejected_before_any_request():
    session = VtexSession(TREE_JSON, {})
    repository = InMemoryProductRepository()
    ctx, _messages = make_ctx(session, repository, category="hogar")

    with pytest.raises(InvalidCategory):
        ScraperDisco().run(ctx)

    assert session.urls == []


def test_no_html_page_is_ever_requested(repository):
    node = f"/{ALMACEN}/{SUB}"
    session = VtexSession(TREE_JSON, {node: node_catalog([(10.0, 2)])})
    repository = InMemoryProductRepository()
    ctx, _messages = make_ctx(session, repository)

    ScraperDisco().run(ctx)

    assert all("/api/catalog_system/" in url for url in session.urls)


def _set_event():
    event = threading.Event()
    event.set()
    return event
