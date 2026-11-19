"""La Anónima scraper: offline behavior against canned site HTML.

HiperLibertad's domain 301s to laanonima.com.ar and the VTEX API the legacy
module consumed answers 403, so this module is a new collector, not a port.
The tests pin the three facts the design relies on: the category tree lives in
the navigation menu, each category page embeds the whole product list as a
JSON-LD ``ItemList``, and a n2 node already contains its n3 children (so the
run must never request both).
"""
import threading
from types import SimpleNamespace

import pytest

from api.scrapers.base import ScrapeContext
from api.scrapers.laanonima import ScraperLaAnonima, detail_url, gtin_of
from tests.fakes import InMemoryProductRepository

# -- fakes ------------------------------------------------------------------


class FakeResponse:
    """A canned response with a status code and a raw HTML body."""

    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text


class FakeSession:
    """Offline stand-in for the shared HTTP session.

    Returns the queued responses in order and raises if the scraper asks for
    more URLs than the test queued, so an unexpected request fails loudly.
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


@pytest.fixture(autouse=True)
def fast_sleep(monkeypatch):
    """Neutralise the real rate-limiting wait: unit tests never sleep."""
    recorder = SimpleNamespace(requests=[])

    def fake_sleep(self, seconds):
        recorder.requests.append(seconds)
        return self.should_stop()

    monkeypatch.setattr(ScrapeContext, "sleep", fake_sleep)
    return recorder


# -- canned site HTML --------------------------------------------------------

ALMACEN_URL = "https://www.laanonima.com.ar/almacen/n1_512/"
DESAYUNO_URL = "https://www.laanonima.com.ar/desayuno-y-merienda/n2_521/"
SNACKS_URL = "https://www.laanonima.com.ar/snacks/n2_522/"
BEBIDAS_URL = "https://www.laanonima.com.ar/bebidas/n1_513/"
AGUAS_URL = "https://www.laanonima.com.ar/aguas/n2_530/"
MASCOTAS_URL = "https://www.laanonima.com.ar/mascotas/n1_877/"

# The real page carries one navigation menu with the whole site tree nested
# n1 -> n2 -> n3. Bebidas is deliberately present: a run must not walk it.
MENU_HTML = f"""
<html><body>
<ul class="menu n1">
  <li>
    <a href="{ALMACEN_URL}" class="color333333 menu-n1">Almacen</a>
    <ul class="menu n2">
      <li>
        <a href="{DESAYUNO_URL}" class="color333333 menu-n2">Desayuno y Merienda</a>
        <ul class="menu n3">
          <li><a href="https://www.laanonima.com.ar/galletitas-dulces/n3_598/" class="color333333 menu-n3">Galletitas Dulces</a></li>
        </ul>
      </li>
      <li><a href="{SNACKS_URL}" class="color333333 menu-n2">Snacks</a></li>
    </ul>
  </li>
  <li>
    <a href="{BEBIDAS_URL}" class="color333333 menu-n1">Bebidas</a>
    <ul class="menu n2">
      <li><a href="{AGUAS_URL}" class="color333333 menu-n2">Aguas</a></li>
    </ul>
  </li>
  <li>
    <a href="{MASCOTAS_URL}" class="color333333 menu-n1">Mascotas</a>
  </li>
</ul>
</body></html>
"""


def item_list_script(*products):
    """The ``<script>`` block of one JSON-LD ItemList, standalone."""
    entries = ", ".join(
        '{"@type": "ListItem", "position": %d, "item": {"@type": "Product", '
        '"name": %s, "url": %s, "offers": %s}}' % (position, name, url, offers)
        for position, (name, url, offers) in enumerate(products, start=1))
    return ('<script type="application/ld+json">{"@context": '
            '"https://schema.org", "@type": "ItemList", '
            f'"itemListElement": [{entries}]}}</script>')


def n1_page(*products):
    """A real n1 page: the navigation menu plus the page's own ItemList.

    ``mascotas`` measured exactly this shape: the menu carries its
    ``a.menu-n1`` anchor but no ``a.menu-n2`` under it, while the page
    itself embeds the JSON-LD ``ItemList`` of its products.
    """
    return MENU_HTML.replace(
        "</body></html>", item_list_script(*products) + "</body></html>")


def item_list_html(*products):
    """A category page carrying one JSON-LD ItemList and a breadcrumb."""
    breadcrumb = ('<script type="application/ld+json">{"@context": '
                  '"https://schema.org", "@type": "BreadcrumbList", '
                  '"itemListElement": [{"@type": "ListItem", '
                  '"position": 1, "name": "Almacen"}]}</script>')
    return f"""<html><head>
{breadcrumb}
{item_list_script(*products)}
</head><body></body></html>"""


def product(name, art_id, price=1500):
    """One Product as the site's JSON-LD encodes it."""
    return (f'"{name}"',
            f'"https://www.laanonima.com.ar/{art_id}/art_{art_id}/"',
            f'{{"@type": "Offer", "price": {price}, "priceCurrency": "ARS"}}')


GALLETITAS_URL = "https://www.laanonima.com.ar/galletitas-dulces/n3_598/"


def make_ctx(session, repository, *, category="almacen", stop_event=None,
             browser_factory=None):
    messages: list[str] = []
    ctx = ScrapeContext(
        slug=ScraperLaAnonima.slug, label=ScraperLaAnonima.label,
        category=category, stop_event=stop_event or threading.Event(),
        report=messages.append, repository=repository,
        browser_factory=browser_factory,
        http_factory=lambda: session)
    return ctx, messages


def stored_documents(repository):
    return [{key: value for key, value in doc.items()
             if key not in ("_id", "scraped_at")}
            for doc in repository.documents]


# -- 1. identity -------------------------------------------------------------


def test_identity_replaces_the_dead_hiperlibertad_brand():
    assert ScraperLaAnonima.slug == "laanonima"
    assert ScraperLaAnonima.label == "La Anónima"
    # Mascotas is no longer declared (comparator-focus F-1); the leaf
    # handling it exercised stays in the code and in its own tests.
    assert ScraperLaAnonima.categories == (
        "almacen", "bebidas", "lacteos-y-frescos", "congelados",
        "frutas-y-verduras", "carniceria", "perfumeria", "limpieza")


def test_the_categories_tuple_and_the_node_dictionary_agree():
    """The tuple drives ``validate_category`` and the dict the discovery
    URL: they must list exactly the same eight keys, in the same order."""
    assert tuple(ScraperLaAnonima.CATEGORY_NODES) == (
        ScraperLaAnonima.categories)


def test_discovery_reads_the_almacen_n2_nodes_from_the_menu():
    session = FakeSession([FakeResponse(200, MENU_HTML),
                           FakeResponse(200, item_list_html()),
                           FakeResponse(200, item_list_html())])
    ctx, _messages = make_ctx(session, InMemoryProductRepository())

    nodes = ScraperLaAnonima()._discover_nodes(ctx, ALMACEN_URL)

    assert nodes == [("desayuno-y-merienda", "Desayuno y Merienda",
                      DESAYUNO_URL),
                     ("snacks", "Snacks", SNACKS_URL)]


def test_discovery_never_returns_another_top_category_or_an_n3_child():
    session = FakeSession([FakeResponse(200, MENU_HTML)])
    ctx, _messages = make_ctx(session, InMemoryProductRepository())

    nodes = ScraperLaAnonima()._discover_nodes(ctx, ALMACEN_URL)

    urls = [url for _slug, _label, url in nodes]
    assert BEBIDAS_URL not in urls
    assert AGUAS_URL not in urls
    assert GALLETITAS_URL not in urls


# -- 2. happy path: URLs, documents, calls ----------------------------------


def test_full_run_requests_the_menu_then_one_url_per_n2_node_and_stores_it(
        repository):
    session = FakeSession([
        FakeResponse(200, MENU_HTML),
        FakeResponse(200, item_list_html(
            product("Galletitas Dulces 500 gr", "2123642", 5100))),
        FakeResponse(200, item_list_html(
            product("Papas Fritas 90 gr", "2706520", 2500))),
    ])
    ctx, messages = make_ctx(session, repository)

    ScraperLaAnonima().run(ctx)

    assert session.urls == [ALMACEN_URL, DESAYUNO_URL, SNACKS_URL]
    assert repository.calls == [
        ("La Anónima", "almacen", "desayuno-y-merienda", 1),
        ("La Anónima", "almacen", "snacks", 1),
    ]
    assert stored_documents(repository) == [
        {"supermercado": "La Anónima", "name": "Galletitas Dulces",
         "unidad": "500 gr", "brand": "", "sku": "2123642", "price": 5100,
         "categoria": "almacen", "subcategoria": "desayuno-y-merienda"},
        {"supermercado": "La Anónima", "name": "Papas Fritas",
         "unidad": "90 gr", "brand": "", "sku": "2706520", "price": 2500,
         "categoria": "almacen", "subcategoria": "snacks"},
    ]
    assert "PROCESO TERMINADO" in messages


def test_a_node_without_products_is_not_saved_and_leaves_no_empty_slice(
        repository):
    session = FakeSession([FakeResponse(200, MENU_HTML),
                           FakeResponse(200, item_list_html()),
                           FakeResponse(200, item_list_html())])
    ctx, _messages = make_ctx(session, repository)

    ScraperLaAnonima().run(ctx)

    assert repository.calls == []
    assert repository.documents == []


# -- 3. parsing rules --------------------------------------------------------


def test_price_comes_from_the_offers_block_and_missing_offers_store_zero():
    session = FakeSession([
        FakeResponse(200, MENU_HTML),
        FakeResponse(200, """<html><head>
<script type="application/ld+json">{"@context": "https://schema.org",
 "@type": "ItemList", "itemListElement": [
 {"@type": "ListItem", "position": 1, "item": {"@type": "Product",
  "name": "Yerba Mate 1 kg", "url": "https://www.laanonima.com.ar/y/art_900/"}},
 {"@type": "ListItem", "position": 2, "item": {"@type": "Product",
  "name": "Te Comun 25 u", "url": "https://www.laanonima.com.ar/t/art_901/",
  "offers": {"@type": "Offer", "price": 1800, "priceCurrency": "ARS"}}}]}
</script></head></html>"""),
        FakeResponse(200, item_list_html()),
    ])
    repository = InMemoryProductRepository()
    ctx, _messages = make_ctx(session, repository)

    ScraperLaAnonima().run(ctx)

    stored = stored_documents(repository)
    # ``name_parse`` only knows kg/g/ml/lt/cc, so "25 u" (unidades) stays in
    # the name and the unit is empty. That is the shared helper's behavior for
    # every scraper, not something this module may change.
    assert [(doc["name"], doc["unidad"], doc["price"], doc["sku"])
            for doc in stored] == [
        ("Yerba Mate", "1 kg", 0, "900"),
        ("Te Comun 25 u", "", 1800, "901"),
    ]


def test_dedupe_is_by_art_id_so_distinct_variants_sharing_a_prefix_survive():
    """The legacy substring guard dropped these; sku identity keeps both."""
    session = FakeSession([
        FakeResponse(200, MENU_HTML),
        FakeResponse(200, item_list_html(
            product("Atun al Natural 160 gr", "1001", 5100),
            product("Atun al Natural sin sal 160 gr", "1002", 5200))),
        FakeResponse(200, item_list_html()),
    ])
    repository = InMemoryProductRepository()
    ctx, _messages = make_ctx(session, repository)

    ScraperLaAnonima().run(ctx)

    assert [doc["sku"] for doc in stored_documents(repository)] == \
        ["1001", "1002"]


def test_the_same_art_id_twice_in_one_node_is_stored_once():
    repeated = product("Atun al Natural 160 gr", "1001", 5100)
    session = FakeSession([
        FakeResponse(200, MENU_HTML),
        FakeResponse(200, item_list_html(repeated, repeated)),
        FakeResponse(200, item_list_html()),
    ])
    repository = InMemoryProductRepository()
    ctx, _messages = make_ctx(session, repository)

    ScraperLaAnonima().run(ctx)

    assert [doc["sku"] for doc in stored_documents(repository)] == ["1001"]


# -- 4. failure modes --------------------------------------------------------


def test_a_node_without_a_jsonld_item_list_is_reported_and_the_run_continues(
        repository):
    session = FakeSession([
        FakeResponse(200, MENU_HTML),
        FakeResponse(200, "<html><body>roto</body></html>"),
        FakeResponse(200, item_list_html(
            product("Papas Fritas 90 gr", "2706520", 2500))),
    ])
    ctx, messages = make_ctx(session, repository)

    ScraperLaAnonima().run(ctx)

    assert repository.calls == [("La Anónima", "almacen", "snacks", 1)]
    assert any("desayuno-y-merienda" in message for message in messages)


def test_a_status_other_than_200_is_reported_and_never_saved(repository):
    session = FakeSession([FakeResponse(200, MENU_HTML),
                           FakeResponse(500, ""),
                           FakeResponse(200, item_list_html())])
    ctx, messages = make_ctx(session, repository)

    ScraperLaAnonima().run(ctx)

    assert repository.calls == []
    assert any("500" in message for message in messages)


def test_a_menu_without_the_almacen_node_saves_nothing_and_says_so(
        repository):
    """A site redesign must fail loudly instead of silently saving nothing."""
    session = FakeSession([FakeResponse(200, "<html><body>sin menu</body>"
                                             "</html>")])
    ctx, messages = make_ctx(session, repository)

    ScraperLaAnonima().run(ctx)

    assert repository.calls == []
    assert any("subcategor" in message.lower() for message in messages)


# -- 5. stop and infrastructure seams ---------------------------------------


def test_stop_between_nodes_never_requests_the_next_node(repository):
    stop_event = threading.Event()
    session = FakeSession([FakeResponse(200, MENU_HTML),
                           FakeResponse(200, item_list_html(
                               product("Galletitas Dulces 500 gr", "1", 100)))],
                          stop_event=stop_event, flip_stop_on=1)
    ctx, messages = make_ctx(session, repository, stop_event=stop_event)

    ScraperLaAnonima().run(ctx)

    assert session.urls == [ALMACEN_URL, DESAYUNO_URL]
    # A stopped run must not claim it finished.
    assert messages[-1] == "PROCESO DETENIDO"
    assert "PROCESO TERMINADO" not in messages


def test_a_pre_cancelled_run_is_inert():
    def forbidden():
        raise AssertionError("no run may build a browser")

    session = FakeSession([])
    ctx, messages = make_ctx(session, InMemoryProductRepository(),
                             stop_event=_set_event(),
                             browser_factory=forbidden)

    ScraperLaAnonima().run(ctx)

    assert session.urls == []
    assert messages == []


def test_no_browser_is_ever_built(repository):
    def forbidden():
        raise AssertionError("La Anónima is scraped with plain HTTP only")

    session = FakeSession([FakeResponse(200, MENU_HTML),
                           FakeResponse(200, item_list_html(
                               product("Galletitas Dulces 500 gr", "1", 100))),
                           FakeResponse(200, item_list_html())])
    ctx, _messages = make_ctx(session, repository, browser_factory=forbidden)

    ScraperLaAnonima().run(ctx)


def test_the_dead_vtex_host_is_never_requested(repository):
    session = FakeSession([FakeResponse(200, MENU_HTML),
                           FakeResponse(200, item_list_html()),
                           FakeResponse(200, item_list_html())])
    ctx, _messages = make_ctx(session, repository)

    ScraperLaAnonima().run(ctx)

    assert not any("hiperlibertad" in url for url in session.urls)


# -- 6. the declared categories and the leaf n1 (wave A) ---------------------


def test_discovery_returns_empty_for_a_leaf_n1_with_no_n2_children():
    """The ``mascotas`` anchor exists in the menu but carries no
    ``a.menu-n2`` under it: that is a leaf (W-2), reported as ``[]`` —
    never collapsed with the missing-anchor case."""
    session = FakeSession([FakeResponse(200, MENU_HTML)])
    ctx, messages = make_ctx(session, InMemoryProductRepository())

    nodes = ScraperLaAnonima()._discover_nodes(ctx, MASCOTAS_URL)

    assert nodes == []
    assert messages == []


def test_discovery_returns_none_when_the_anchor_is_absent():
    """A n1 URL the menu does not list at all is a site change (W-3):
    ``None``, the loud report of the caller — a different fact from a
    leaf."""
    session = FakeSession([FakeResponse(200, MENU_HTML)])
    ctx, messages = make_ctx(session, InMemoryProductRepository())

    nodes = ScraperLaAnonima()._discover_nodes(
        ctx, "https://www.laanonima.com.ar/jardin/n1_999/")

    assert nodes is None


def test_a_failed_menu_read_never_scrapes_the_page_as_a_leaf(repository):
    """A menu read that failed (network, status) is not a leaf: the run
    reports it and stops — it must not re-request the same URL as the
    leaf's n1 page."""
    session = FakeSession([FakeResponse(500, "")])
    ctx, messages = make_ctx(session, repository)

    ScraperLaAnonima().run(ctx)

    assert session.urls == [ALMACEN_URL]
    assert repository.calls == []
    assert any("Error 500" in message for message in messages)
    assert messages[-1] == "PROCESO TERMINADO"


def test_a_leaf_category_scrapes_its_own_page_and_stores_its_slug(
        repository, monkeypatch):
    """W-2: a leaf n1 is scraped as one node — the n1 page itself is the
    collection scope and its own slug is the stored ``subcategoria``
    (``mascotas``: 201 items measured on the live page). The category is a
    fixture here on purpose: mascotas is no longer declared (comparator
    focus F-1) and the leaf behaviour it exercised must survive that."""
    monkeypatch.setattr(ScraperLaAnonima, "categories", ("mascotas",))
    monkeypatch.setattr(ScraperLaAnonima, "CATEGORY_NODES",
                        {"mascotas": MASCOTAS_URL})
    page = n1_page(product("Alimento Pro Plan 3 kg", "3001", 18000))
    session = FakeSession([FakeResponse(200, page),   # the menu read
                           FakeResponse(200, page)])  # the leaf's own page
    ctx, messages = make_ctx(session, repository, category="mascotas")

    ScraperLaAnonima().run(ctx)

    assert session.urls == [MASCOTAS_URL, MASCOTAS_URL]
    assert repository.calls == [("La Anónima", "mascotas", "mascotas", 1)]
    assert stored_documents(repository) == [
        {"supermercado": "La Anónima", "name": "Alimento Pro Plan",
         "unidad": "3 kg", "brand": "", "sku": "3001", "price": 18000,
         "categoria": "mascotas", "subcategoria": "mascotas"}]
    assert any("mascotas no tiene subcategorías" in message
               for message in messages)
    assert messages[-1] == "PROCESO TERMINADO"


def test_a_leaf_page_without_an_item_list_is_reported_and_the_run_continues(
        repository, monkeypatch):
    """A leaf whose page carries no ItemList is reported and skipped —
    the run goes on to the next declared category instead of dying there
    (an empty leaf must never mask the other categories)."""
    monkeypatch.setattr(ScraperLaAnonima, "categories",
                        ("mascotas", "almacen"))
    monkeypatch.setattr(ScraperLaAnonima, "CATEGORY_NODES", {
        "mascotas": MASCOTAS_URL,
        "almacen": ALMACEN_URL,
    })
    session = FakeSession([
        FakeResponse(200, MENU_HTML),   # mascotas: menu read (leaf)
        FakeResponse(200, MENU_HTML),   # mascotas: own page, no ItemList
        FakeResponse(200, MENU_HTML),   # almacen: menu read
        FakeResponse(200, item_list_html(
            product("Galletitas Dulces 500 gr", "2123642", 5100))),
        FakeResponse(200, item_list_html()),            # snacks, empty
    ])
    ctx, messages = make_ctx(session, repository, category=None)

    ScraperLaAnonima().run(ctx)

    assert any("Sin datos en mascotas" in message for message in messages)
    assert repository.calls == [
        ("La Anónima", "almacen", "desayuno-y-merienda", 1)]
    assert messages[-1] == "PROCESO TERMINADO"


def test_a_run_over_the_declared_categories_saves_one_slice_per_category(
        repository, monkeypatch):
    """Without a ``--category`` filter the run walks every declared
    category, and every slice carries its own ``categoria`` — the wave-A
    goal of the whole editable shelf."""
    monkeypatch.setattr(ScraperLaAnonima, "categories",
                        ("almacen", "bebidas"))
    session = FakeSession([
        FakeResponse(200, MENU_HTML),   # almacen menu
        FakeResponse(200, item_list_html(
            product("Galletitas Dulces 500 gr", "2123642", 5100))),
        FakeResponse(200, item_list_html(
            product("Papas Fritas 90 gr", "2706520", 2500))),
        FakeResponse(200, MENU_HTML),   # bebidas menu
        FakeResponse(200, item_list_html(
            product("Coca Cola 2 lt", "3100001", 1234))),
    ])
    ctx, messages = make_ctx(session, repository, category=None)

    ScraperLaAnonima().run(ctx)

    assert session.urls == [ALMACEN_URL, DESAYUNO_URL, SNACKS_URL,
                            BEBIDAS_URL, AGUAS_URL]
    assert repository.calls == [
        ("La Anónima", "almacen", "desayuno-y-merienda", 1),
        ("La Anónima", "almacen", "snacks", 1),
        ("La Anónima", "bebidas", "aguas", 1),
    ]
    assert {doc["categoria"]
            for doc in stored_documents(repository)} == {"almacen",
                                                         "bebidas"}
    assert messages[-1] == "PROCESO TERMINADO"


def _set_event():
    event = threading.Event()
    event.set()
    return event


# -- EAN enrichment site knowledge (ean-enrichment T1) ------------------------


def test_detail_url_builds_the_slug_free_route():
    """``https://www.laanonima.com.ar/x/art_<id>/`` answers exactly like the
    canonical ``.../<slug>/art_<id>/``: any slug works because the route only
    needs *a* slug and ignores its value (measured 15/15 sampled products,
    ``odd/tasks/ean-enrichment.md``). The ``x`` is therefore decorative and
    must NOT be derived from the product name — the id is the stored ``sku``.
    """
    assert detail_url("3001") == "https://www.laanonima.com.ar/x/art_3001/"
    assert detail_url("2123642") == \
        "https://www.laanonima.com.ar/x/art_2123642/"


def product_page_json_ld(value):
    """A product detail page whose JSON-LD ``Product`` block carries ``gtin``."""
    return (
        '<html><head>'
        '<script type="application/ld+json">'
        '{"@context": "https://schema.org", "@type": "Product", '
        f'"name": "Coca Cola 2 lt", "gtin": "{value}", '
        '"offers": {"@type": "Offer", "price": 1234}}'
        '</script>'
        '</head><body></body></html>')


def test_gtin_of_reads_the_product_block():
    assert gtin_of(product_page_json_ld("7790895000123")) == "7790895000123"


def test_gtin_of_reads_a_product_inside_a_block_array():
    """Some pages embed the JSON-LD as a list of blocks instead of one object
    or an ``@graph``; the ``Product`` element is still found."""
    html = (
        '<script type="application/ld+json">'
        '[{"@type": "BreadcrumbList"}, '
        '{"@type": "Product", "gtin": "7791234567890"}]'
        '</script>')
    assert gtin_of(html) == "7791234567890"


def test_gtin_of_returns_none_on_a_category_item_list_page():
    """The category pages only carry an ``ItemList`` (no ``gtin``, measured):
    a category page must extract nothing, not the first number around."""
    assert gtin_of(item_list_html(
        product("Coca Cola 2 lt", "3100001", 1234))) is None


def test_gtin_of_returns_none_when_there_is_no_json_ld():
    assert gtin_of("<html><body><p>hola</p></body></html>") is None


def test_gtin_of_returns_none_when_the_gtin_is_not_digits():
    assert gtin_of(product_page_json_ld("")) is None
    assert gtin_of(product_page_json_ld("7790895-000123")) is None


def test_gtin_of_skips_a_broken_json_block_and_reads_the_next():
    html = (
        '<script type="application/ld+json">not json at all</script>'
        + product_page_json_ld("7790895000123"))
    assert gtin_of(html) == "7790895000123"
