"""Disco scraper: offline behavior against the VTEX catalog API.

`/almacen`'s HTML needs a browser; the catalog API does not. The tree at
``/api/catalog_system/pub/category/tree/2`` and the search endpoint
``/api/catalog_system/pub/products/search/<path>`` (206 with a
``resources: from-to/total`` header, measured on 2026-11-05) answer everything
the HTML path scraped. The offset ceiling is 2550 items (``_from=2500&_to=2550``
→ 400), and nodes whose priced subset exceeds it are read through inclusive
``fq=P:[lo TO hi]`` price buckets bisected until each one fits; a boundary
product shows up in two buckets and the ``productId`` dedupe collapses it.

The collection scope is the priced subset (D-3): the unpriced cluster
(``Price 0`` / ``IsAvailable: false``) is one atomic mass no price range can
split, so collection runs on ``fq=P:[0.01 TO <priced max>]`` (D-3a — the lower
bound is the constant floor, never ``OrderByPriceASC``, whose unfiltered first
window returned 479.0 live while the unpriced atom sat below it) and the exact
count of omitted unpriced entries is reported per child.

These tests pin that design offline: the fake session models the measured API
— including the unpriced atom the first live run fell over — and nothing here
opens a browser, touches an HTML page or the network.
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

FLOOR = 0.01
CEIL = 100000000
PRICED = (FLOOR, CEIL)   # D-3: every collection request carries this scope

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


def product(name, product_id, price=1000.0, brand="Marca", offer=True,
            ean="7790272001005"):
    """One product in the shape the VTEX search API returns.

    ``price=0.0`` is the unpriced cluster the live run measured:
    ``IsAvailable: false`` rows whose ``commertialOffer.Price`` is 0.
    ``ean`` is the barcode the live probe verified on every ``items[]``
    entry; ``ean=None`` omits the key.
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


def _available(entry):
    """A catalog entry is an available offer unless flagged out of stock."""
    return len(entry) < 3 or bool(entry[2])


class VtexSession:
    """Offline stand-in for the measured catalog API.

    ``catalog`` maps a node path (``/almacen/aceites-y-vinagres``) to the
    ordered ``(price, product)`` list the search endpoint pages there; a
    price of ``0.0`` is the out-of-stock ``Price 0`` level and an entry may
    carry a trailing ``False`` to flag an out-of-stock row with a stale
    price. ``failures`` is a consumed-on-first-match list of ``(url
    substring, outcome)`` where an outcome is a raising exception, a response
    status, or ``"invalid-json"``; a list outcome burns one element per
    matching request and then reverts to normal behavior, to model transient
    server errors.

    Faithful to the measured API:

    - the unfiltered total includes the out-of-stock entries;
    - every ``fq=P:[lo TO hi]`` request indexes available offers only (plevel
      measured live on ``aceites-y-vinagres``: 200 available of 1 478), so it
      excludes ``Price 0`` entries for every ``lo > 0`` (``0 < 0.01``) but
      holds them whole for ``lo <= 0``;
    - ``O=OrderByPriceASC`` (unfiltered) returns the cheapest **priced**
      available product, not the true minimum — live on ``golosinas`` it
      returned 479.0 while the out-of-stock atom sat below it, which is why
      a lower bound may never be inferred from it;
    - ``O=OrderByPriceDESC`` inside the priced filter returns the true priced
      maximum;
    - any window with ``_to > 2549`` or ``_from >= 2501`` answers 400 (the
      offset ceiling), and an empty result answers 200 with
      ``resources: 0-0/0`` and body ``[]`` — never 206.
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
            if pattern not in url:
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
            if fired == "invalid-json":
                return FakeResponse(200, valid_json=False)
            return FakeResponse(int(fired), text=f"error {fired}")

        parts = urlsplit(url)
        if parts.path.rstrip("/") == "/api/catalog_system/pub/category/tree/2":
            return FakeResponse(200, self.tree)

        query = parse_qs(parts.query)
        start = int((query.get("_from") or ["0"])[0])
        end = int((query.get("_to") or [str(start)])[0])
        order = (query.get("O") or [None])[0]
        price_range = PRICE_RANGE.match((query.get("fq") or [""])[0])
        node = parts.path[len("/api/catalog_system/pub/products/search"):]
        pool = self.catalog.get(node, [])
        if price_range:
            # Measured live: every P filter indexes available offers only.
            lo, hi = float(price_range.group(1)), float(price_range.group(2))
            pool = [entry for entry in pool
                    if _available(entry) and lo <= entry[0] <= hi]
        if order == "OrderByPriceASC":
            # Live measured: the out-of-stock cluster stays out.
            chosen = sorted((entry for entry in pool
                             if _available(entry) and entry[0] > 0),
                            key=lambda entry: entry[0])[:1]
            items = [entry[1] for entry in chosen]
            if not items:
                return FakeResponse(200, [], total=0, first=start, last=end)
            return FakeResponse(206, items, total=len(pool),
                                first=start, last=end)
        if order == "OrderByPriceDESC":
            items = [entry[1] for entry
                     in sorted(pool, key=lambda entry: entry[0])[-1:]]
            if not items:
                return FakeResponse(200, [], total=0, first=start, last=end)
            return FakeResponse(206, items, total=len(pool),
                                first=start, last=end)
        total = len(pool)
        if not total:
            # Verified live: an empty result is 200 with resources 0-0/0,
            # never a 206 — a zero-total bucket is skipped, not fatal.
            return FakeResponse(200, [], total=0, first=start, last=end)
        if end > 2549 or start >= 2501:
            # Verified live: `_from=2500&_to=2549` is the last valid window;
            # `_to=2550` and `_from=2501` both answer 400.
            return FakeResponse(400, text="the offset window is capped")
        items = [entry[1] for entry in pool[start:min(end, total - 1) + 1]]
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


def expected_doc(name, unidad, brand, sku, price, subcategoria,
                 ean="7790272001005"):
    return {"supermercado": "Disco", "name": name, "unidad": unidad,
            "brand": brand, "sku": sku, "price": price, "ean": ean,
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


def paged_windows(urls, node):
    """The bucket/window requests (probes ask for exactly one item)."""
    probe = re.compile(r"\?_from=0&_to=0(&|$)")
    return [url for url in urls
            if url.startswith(f"{SEARCH_URL}{node}?_from=")
            and not probe.search(url)]


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


def test_a_category_missing_from_the_tree_fails_the_run():
    """'almacen' is a registered category but absent from the measured tree:
    the run must fail (R3-002) instead of ending as a success with zero
    products, so a renamed or removed site path cannot look healthy."""
    tree = [dict(TREE_JSON[0])]  # only 'tecnología', no 'almacén' node
    session = VtexSession(tree, {})
    repository = InMemoryProductRepository()
    ctx, messages = make_ctx(session, repository, category=ALMACEN)

    with pytest.raises(RuntimeError):
        ScraperDisco().run(ctx)

    assert session.urls == [TREE_URL]
    assert repository.calls == []
    assert any("almacen" in message for message in messages)
    assert not any("PROCESO TERMINADO" in message for message in messages)


def test_a_tree_node_without_usable_children_fails_the_run():
    """'almacen' resolves in the tree but yields no usable children: the run
    must fail too (R3-002), with a report distinguishable from the
    missing-node one so the operator can tell an empty node from a renamed
    path."""
    tree = [dict(TREE_JSON[0]), dict(TREE_JSON[1])]
    tree[1]["children"] = []
    session = VtexSession(tree, {})
    repository = InMemoryProductRepository()
    ctx, messages = make_ctx(session, repository, category=ALMACEN)

    with pytest.raises(RuntimeError):
        ScraperDisco().run(ctx)

    assert session.urls == [TREE_URL]
    assert repository.calls == []
    assert any("no tiene subcategorías" in message for message in messages)
    assert not any("PROCESO TERMINADO" in message for message in messages)


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


# -- 2. the priced scope (D-3) -----------------------------------------------


def test_the_fake_models_the_out_of_stock_atom_and_the_price_bounds():
    """Fake fidelity, pinned directly: the unfiltered total includes the
    out-of-stock rows (stale price and Price 0), every P filter indexes
    available offers only, and OrderByPriceASC reports the cheapest priced
    product — never the out-of-stock minimum."""
    node = f"/{ALMACEN}/{SUB}"
    entries = [(0.0, product("Sin precio A", 1, 0.0)),
               (0.0, product("Sin precio B", 2, 0.0)),
               (479.0, product("Con precio C", 3, 479.0)),
               (1000.0, product("Con precio D", 4, 1000.0)),
               # Out of stock with a stale, unusable price (measured live).
               (8.69, product("Sin stock E", 5, 8.69), False)]
    session = VtexSession(TREE_JSON, {node: entries})

    whole = session.get(window_url(node, 0))
    assert whole.headers["resources"] == "0-49/5"
    assert [p["productId"] for p in whole.json()] == [1, 2, 3, 4, 5]

    atom_with_zero_lo = session.get(window_url(node, 0, price_range=(0, 1000)))
    assert [p["productId"] for p in atom_with_zero_lo.json()] == [1, 2, 3, 4]

    priced_scope = session.get(window_url(node, 0, price_range=PRICED))
    assert [p["productId"] for p in priced_scope.json()] == [3, 4]

    atom_cluster = session.get(window_url(node, 0, price_range=(0, 0)))
    assert [p["productId"] for p in atom_cluster.json()] == [1, 2]

    asc = session.get(probe_url(node, order="OrderByPriceASC"))
    assert [p["productId"] for p in asc.json()] == [3]

    desc = session.get(probe_url(node, order="OrderByPriceDESC",
                                 price_range=PRICED))
    assert [p["productId"] for p in desc.json()] == [4]


def test_a_priced_subset_under_the_ceiling_is_paged_whole_without_a_gap(
        repository):
    def forbidden():
        raise AssertionError("Disco is scraped through the VTEX API only")

    def fillers():
        return [(400.0 + index, product(f"Diverso test {index} 500 gr",
                                        index, 400.0 + index))
                for index in range(1, 120)]

    node = f"/{ALMACEN}/{SUB}"
    node2 = f"/{ALMACEN}/{SUB2}"
    catalog = {
        node: ([(0.0, product(f"Sin precio {index}", 10000 + index, 0.0))
                for index in range(30)]
               + [(890.0, product("Puré de tomate Arcor 520 g", 122140,
                                  890.0, "Arcor"))] + fillers()),
        node2: [],
    }
    session = VtexSession(TREE_JSON, catalog)
    repository = InMemoryProductRepository()
    ctx, messages = make_ctx(session, repository, browser_factory=forbidden)

    ScraperDisco().run(ctx)

    assert session.urls == [
        TREE_URL,
        probe_url(node),
        probe_url(node, price_range=PRICED),
        window_url(node, 0, price_range=PRICED),
        window_url(node, 50, price_range=PRICED),
        window_url(node, 100, price_range=PRICED),
        probe_url(node2),
    ]
    assert session.timeouts == [30, 90, 90, 90, 90, 90, 90]
    assert all("OrderByPriceASC" not in url for url in session.urls)
    assert repository.calls == [("Disco", ALMACEN, SUB, 120)]
    stored = stored_documents(repository)
    assert stored[0] == expected_doc("Puré de tomate Arcor", "520 g", "Arcor",
                                     "122140", 890.0, SUB)
    assert all(doc["name"] != "Sin precio" for doc in stored)
    assert any("30 sin stock omitidos" in message for message in messages)
    assert not any("faltantes" in message for message in messages)
    assert messages[-1] == "PROCESO TERMINADO"


def test_an_all_out_of_stock_node_reports_the_omission_and_saves_nothing(
        repository):
    node = f"/{ALMACEN}/{SUB}"
    node2 = f"/{ALMACEN}/{SUB2}"
    catalog = {
        node: [(0.0, product(f"Sin precio {index}", index, 0.0))
               for index in range(40)],
        node2: [],
    }
    session = VtexSession(TREE_JSON, catalog)
    repository = InMemoryProductRepository()
    ctx, messages = make_ctx(session, repository)

    ScraperDisco().run(ctx)

    assert session.urls == [TREE_URL, probe_url(node),
                            probe_url(node, price_range=PRICED),
                            probe_url(node2)]
    assert repository.calls == []
    assert repository.documents == []
    assert any("40 sin stock omitidos" in message for message in messages)
    assert messages[-1] == "PROCESO TERMINADO"


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


# -- 3. the ceiled priced subset and the price partition ---------------------


def test_an_oversized_priced_subset_is_bisected_from_the_floor(repository):
    """priced 2700 > MAX_WINDOW, 600 unpriced below: every bucket starts at
    PRICE_FLOOR (never at the OrderByPriceASC value), covers 100 % of the
    priced total, and the 600 omitted unpriced are reported by name. A priced
    5.505 (the split price itself) shows up in both buckets once."""
    node = f"/{ALMACEN}/{SUB}"
    node2 = f"/{ALMACEN}/{SUB2}"
    priced = node_catalog([(1.0, 1300), (5.505, 100), (11.0, 1300)])
    unpriced = [(0.0, product(f"Sin precio {index}", 10000 + index, 0.0))
                for index in range(600)]
    catalog = {node: unpriced + priced, node2: []}
    session = VtexSession(TREE_JSON, catalog)
    repository = InMemoryProductRepository()
    ctx, messages = make_ctx(session, repository)

    ScraperDisco().run(ctx)

    mid = (FLOOR + 11.0) / 2
    assert session.urls[:7] == [
        TREE_URL,
        probe_url(node),
        probe_url(node, price_range=PRICED),
        probe_url(node, order="OrderByPriceDESC", price_range=PRICED),
        probe_url(node, price_range=(FLOOR, 11.0)),
        probe_url(node, price_range=(FLOOR, mid)),
        probe_url(node, price_range=(mid, 11.0)),
    ]
    buckets = session.urls[7:]
    first_bucket = [window_url(node, start, price_range=(FLOOR, mid))
                    for start in range(0, 1400, 50)]
    second_bucket = [window_url(node, start, price_range=(mid, 11.0))
                     for start in range(0, 1400, 50)]
    assert buckets == first_bucket + second_bucket + [probe_url(node2)]
    assert all("OrderByPriceASC" not in url for url in session.urls)
    assert any("600 sin stock omitidos" in message for message in messages)
    assert not any("faltantes" in message for message in messages)
    assert repository.calls == [("Disco", ALMACEN, SUB, 2700)]
    skus = [doc["sku"] for doc in stored_documents(repository)]
    assert len(skus) == len(set(skus)) == 2700
    assert skus.count("1301") == 1  # a boundary product, stored once
    assert messages[-1] == "PROCESO TERMINADO"


def test_bisection_that_cannot_split_reports_the_exact_unreachable_count(
        repository):
    """3000 products share one price: starting from the floor the halves left
    of the price all come back empty (skipped), halving converges, and the
    resulting whole-price bucket only reaches the 2550 ceiling — the 450
    unreachable priced products are reported by name."""
    node = f"/{ALMACEN}/{SUB}"
    node2 = f"/{ALMACEN}/{SUB2}"
    catalog = {node: node_catalog([(100.0, 3000)]), node2: []}
    session = VtexSession(TREE_JSON, catalog)
    repository = InMemoryProductRepository()
    ctx, messages = make_ctx(session, repository)

    ScraperDisco().run(ctx)

    assert session.urls[:5] == [
        TREE_URL,
        probe_url(node),
        probe_url(node, price_range=PRICED),
        probe_url(node, order="OrderByPriceDESC", price_range=PRICED),
        probe_url(node, price_range=(FLOOR, 100.0)),
    ]
    windows = paged_windows(session.urls, node)
    assert len(windows) == 51  # cap 2550 → starts 0..2500 step 50
    assert windows[-1].startswith(
        f"{SEARCH_URL}{node}?_from=2500&_to=2549&fq=P:[")
    # The ceiling is never crossed.
    assert "_to=2550" not in "".join(session.urls)
    assert "_to=" + str(2550) not in "".join(session.urls)
    assert repository.calls == [("Disco", ALMACEN, SUB, 2550)]
    skus = [doc["sku"] for doc in stored_documents(repository)]
    assert len(skus) == len(set(skus)) == 2550
    assert not any("sin precio omitidos" in message for message in messages)
    assert any("450" in message for message in messages)
    assert messages[-1] == "PROCESO TERMINADO"
    assert session.urls[-1] == probe_url(node2)


def test_an_empty_price_bucket_is_skipped_and_the_other_buckets_are_paged(
        repository):
    """A distribution gap inside the priced range (no product between the
    5.505 split and 8.2525): each empty bucket probe answers 200 with
    `0-0/0`, is skipped without failing, the 100 products of the low bucket
    are fully paged, and the single-price remainder converges to a
    ceiling-capped bucket."""
    node = f"/{ALMACEN}/{SUB}"
    node2 = f"/{ALMACEN}/{SUB2}"
    catalog = {node: node_catalog([(6.0, 100), (11.0, 2900)]), node2: []}
    session = VtexSession(TREE_JSON, catalog)
    repository = InMemoryProductRepository()
    ctx, messages = make_ctx(session, repository)

    ScraperDisco().run(ctx)

    split = (FLOOR + 11.0) / 2
    assert probe_url(node, price_range=(FLOOR, split)) in session.urls
    second_split = (split + 11.0) / 2
    third_split = (second_split + 11.0) / 2
    assert probe_url(node, price_range=(second_split, third_split)) \
        in session.urls
    low_bucket = [window_url(node, start, price_range=(split, second_split))
                  for start in (0, 50)]
    assert all(url in session.urls for url in low_bucket)
    skus = [doc["sku"] for doc in stored_documents(repository)]
    assert len(skus) == len(set(skus)) == 100 + 2550
    assert any("350" in message for message in messages)
    assert messages[-1] == "PROCESO TERMINADO"


def test_a_bumped_max_window_hits_the_live_ceiling_and_fails_the_run(
        repository, monkeypatch):
    """The fake enforces the measured API ceiling, so the scraper cannot
    regress without the suite catching it: bump MAX_WINDOW past 2550 and the
    window at 2550+ answers 400, which fails the run loudly."""
    node = f"/{ALMACEN}/{SUB}"
    node2 = f"/{ALMACEN}/{SUB2}"
    session = VtexSession(TREE_JSON, {node: node_catalog([(100.0, 3000)]),
                                      node2: []})
    repository = InMemoryProductRepository()
    ctx, messages = make_ctx(session, repository)
    monkeypatch.setattr(disco_module, "MAX_WINDOW", 10 ** 6)

    with pytest.raises(RuntimeError):
        ScraperDisco().run(ctx)

    # The last legal window (2500..2549) was served; the very next window
    # crossed the ceiling and the fake answered 400.
    assert window_url(node, 2500, price_range=PRICED) in session.urls
    assert window_url(node, 2550, price_range=PRICED) in session.urls
    assert any("Error 400" in message for message in messages)
    assert repository.calls == []


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


def test_a_4xx_is_reported_and_propagates_on_the_first_attempt(
        repository, fast_sleep):
    """A 4xx means the request is wrong, not the server: one request only,
    no backoff sleep, and the run fails (D-9)."""
    node = f"/{ALMACEN}/{SUB}"
    node2 = f"/{ALMACEN}/{SUB2}"
    session = VtexSession(TREE_JSON, {node: node_catalog([(10.0, 70)]),
                                      node2: []},
                          failures=[("_to=49", 400)])
    repository = InMemoryProductRepository()
    ctx, messages = make_ctx(session, repository)

    with pytest.raises(RuntimeError):
        ScraperDisco().run(ctx)

    assert session.urls.count(window_url(node, 0, price_range=PRICED)) == 1
    assert session.urls[:4] == [TREE_URL, probe_url(node),
                                probe_url(node, price_range=PRICED),
                                window_url(node, 0, price_range=PRICED)]
    assert window_url(node, 50, price_range=PRICED) not in session.urls
    assert not any(seconds != 1 for seconds in fast_sleep.requests)
    assert repository.calls == []
    assert any("Error 400" in message for message in messages)


def test_a_transient_500_is_retried_once_and_the_window_succeeds(
        repository, fast_sleep):
    node = f"/{ALMACEN}/{SUB}"
    node2 = f"/{ALMACEN}/{SUB2}"
    session = VtexSession(TREE_JSON, {node: node_catalog([(10.0, 120)]),
                                      node2: []},
                          failures=[("_to=49", [500])])
    repository = InMemoryProductRepository()
    ctx, messages = make_ctx(session, repository)

    ScraperDisco().run(ctx)

    assert session.urls.count(window_url(node, 0, price_range=PRICED)) == 2
    assert window_url(node, 50, price_range=PRICED) in session.urls
    assert [seconds for seconds in fast_sleep.requests if seconds != 1] == [2]
    assert repository.calls == [("Disco", ALMACEN, SUB, 120)]
    assert messages[-1] == "PROCESO TERMINADO"


def test_two_transient_500s_are_retried_with_2_then_4_seconds(
        repository, fast_sleep):
    node = f"/{ALMACEN}/{SUB}"
    node2 = f"/{ALMACEN}/{SUB2}"
    session = VtexSession(TREE_JSON, {node: node_catalog([(10.0, 120)]),
                                      node2: []},
                          failures=[("_to=49", [500, 500])])
    repository = InMemoryProductRepository()
    ctx, messages = make_ctx(session, repository)

    ScraperDisco().run(ctx)

    assert session.urls.count(window_url(node, 0, price_range=PRICED)) == 3
    assert window_url(node, 50, price_range=PRICED) in session.urls
    assert [seconds for seconds in fast_sleep.requests if seconds != 1] == [2, 4]
    assert repository.calls == [("Disco", ALMACEN, SUB, 120)]
    assert messages[-1] == "PROCESO TERMINADO"


def test_three_500s_exhaust_the_retries_and_fail_the_run(
        repository, fast_sleep):
    node = f"/{ALMACEN}/{SUB}"
    node2 = f"/{ALMACEN}/{SUB2}"
    session = VtexSession(TREE_JSON, {node: node_catalog([(10.0, 70)]),
                                      node2: []},
                          failures=[("_to=49", [500, 500, 500])])
    repository = InMemoryProductRepository()
    ctx, messages = make_ctx(session, repository)

    with pytest.raises(RuntimeError):
        ScraperDisco().run(ctx)

    assert session.urls.count(window_url(node, 0, price_range=PRICED)) == 3
    assert [seconds for seconds in fast_sleep.requests if seconds != 1] == [2, 4]
    assert repository.calls == []
    assert any("500" in message for message in messages)


def test_a_transient_network_error_is_retried_and_succeeds(
        repository, fast_sleep):
    node = f"/{ALMACEN}/{SUB}"
    node2 = f"/{ALMACEN}/{SUB2}"
    session = VtexSession(TREE_JSON, {node: node_catalog([(10.0, 70)]),
                                      node2: []},
                          failures=[("_to=49", [RuntimeError("network down")])])
    repository = InMemoryProductRepository()
    ctx, messages = make_ctx(session, repository)

    ScraperDisco().run(ctx)

    assert session.urls.count(window_url(node, 0, price_range=PRICED)) == 2
    assert [seconds for seconds in fast_sleep.requests if seconds != 1] == [2]
    assert repository.calls == [("Disco", ALMACEN, SUB, 70)]
    assert messages[-1] == "PROCESO TERMINADO"


def test_a_stop_during_backoff_ends_the_run_without_failing(
        repository, fast_sleep):
    """A stop requested while the 2 s backoff of a failed window runs must
    end the run as PROCESO DETENIDO with whatever was already collected —
    never as failed. Window 0 was collected; window 1's first attempt answers
    500 and the stop fires during its backoff."""
    stop_event = threading.Event()
    node = f"/{ALMACEN}/{SUB}"
    node2 = f"/{ALMACEN}/{SUB2}"
    session = VtexSession(TREE_JSON, {node: node_catalog([(10.0, 120)]),
                                      node2: []},
                          failures=[("_to=99", [500])],
                          stop_event=stop_event, flip_stop_on=5)
    repository = InMemoryProductRepository()
    ctx, messages = make_ctx(session, repository, stop_event=stop_event)

    ScraperDisco().run(ctx)

    assert window_url(node, 0, price_range=PRICED) in session.urls
    assert session.urls.count(
        window_url(node, 50, price_range=PRICED)) == 1  # no retry beyond
    assert window_url(node, 100, price_range=PRICED) not in session.urls
    assert repository.calls == [("Disco", ALMACEN, SUB, 50)]
    assert 2 in fast_sleep.requests
    assert messages[-1] == "PROCESO DETENIDO"
    assert "PROCESO TERMINADO" not in messages


# -- 5. stop -----------------------------------------------------------------


def test_stop_during_paging_saves_the_partial_documents_and_reports_it(
        repository):
    stop_event = threading.Event()
    node = f"/{ALMACEN}/{SUB}"
    node2 = f"/{ALMACEN}/{SUB2}"
    session = VtexSession(TREE_JSON, {node: node_catalog([(10.0, 120)]),
                                      node2: []},
                          stop_event=stop_event, flip_stop_on=4)
    repository = InMemoryProductRepository()
    ctx, messages = make_ctx(session, repository, stop_event=stop_event)

    ScraperDisco().run(ctx)

    assert window_url(node, 0, price_range=PRICED) in session.urls
    assert window_url(node, 50, price_range=PRICED) not in session.urls
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


def test_ean_comes_from_the_item_and_a_missing_ean_stores_empty(repository):
    """The live probe verified every ``items[]`` entry carries an ``ean``
    string; an item without the key must not crash the run and stores
    ``""``."""
    node = f"/{ALMACEN}/{SUB}"
    node2 = f"/{ALMACEN}/{SUB2}"
    catalog = {
        node: [
            (1200.5, product("Con EAN 500 gr", 801, 1200.5,
                             ean="7794567890123")),
            (1200.5, product("Sin EAN 500 gr", 802, 1200.5, ean=None)),
        ],
        node2: [],
    }
    session = VtexSession(TREE_JSON, catalog)
    repository = InMemoryProductRepository()
    ctx, _messages = make_ctx(session, repository)

    ScraperDisco().run(ctx)

    stored = stored_documents(repository)
    assert [(doc["sku"], doc["ean"]) for doc in stored] == [
        ("801", "7794567890123"),
        ("802", ""),
    ]


# -- 6. field mapping and validation -----------------------------------------


def test_price_comes_from_the_offer_and_a_missing_offer_stores_zero(repository):
    """An unpriced atom (Price 0.0) is intentionally not requested (D-3); a
    product whose offer is absent but which arrives inside a priced window
    still stores `price: 0`."""
    node = f"/{ALMACEN}/{SUB}"
    node2 = f"/{ALMACEN}/{SUB2}"
    catalog = {
        node: [
            (0.0, product("Solo no disponible", 902, 0.0)),
            # Engine priced 1800.5 so the window delivers it; its own offer
            # carries no sellers, so the stored price is 0.
            (1800.5, product("Sin oferta 500 gr", 900, offer=False)),
            (1800.5, product("Con oferta 500 gr", 901, 1800.5)),
        ],
        node2: [],
    }
    session = VtexSession(TREE_JSON, catalog)
    repository = InMemoryProductRepository()
    ctx, messages = make_ctx(session, repository)

    ScraperDisco().run(ctx)

    assert any("sin stock omitidos" in message for message in messages)
    stored = stored_documents(repository)
    assert [(doc["name"], doc["price"], doc["sku"]) for doc in stored] == [
        ("Sin oferta", 0, "900"),
        ("Con oferta", 1800.5, "901"),
    ]
    assert all(doc["name"] != "Solo no disponible" for doc in stored)


def test_an_unknown_category_is_rejected_before_any_request():
    session = VtexSession(TREE_JSON, {})
    repository = InMemoryProductRepository()
    ctx, _messages = make_ctx(session, repository, category="hogar")

    with pytest.raises(InvalidCategory):
        ScraperDisco().run(ctx)

    assert session.urls == []


def test_no_html_page_is_ever_requested(repository):
    node = f"/{ALMACEN}/{SUB}"
    node2 = f"/{ALMACEN}/{SUB2}"
    session = VtexSession(TREE_JSON, {node: node_catalog([(10.0, 2)]),
                                      node2: []})
    repository = InMemoryProductRepository()
    ctx, _messages = make_ctx(session, repository)

    ScraperDisco().run(ctx)

    assert all("/api/catalog_system/" in url for url in session.urls)


def _set_event():
    event = threading.Event()
    event.set()
    return event
