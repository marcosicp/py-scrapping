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
from api.scrapers.laanonima import ScraperLaAnonima
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
</ul>
</body></html>
"""


def item_list_html(*products):
    """A category page carrying one JSON-LD ItemList and a breadcrumb."""
    entries = ", ".join(
        '{"@type": "ListItem", "position": %d, "item": {"@type": "Product", '
        '"name": %s, "url": %s, "offers": %s}}' % (position, name, url, offers)
        for position, (name, url, offers) in enumerate(products, start=1))
    return f"""<html><head>
<script type="application/ld+json">{{"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [{{"@type": "ListItem", "position": 1, "name": "Almacen"}}]}}</script>
<script type="application/ld+json">{{"@context": "https://schema.org", "@type": "ItemList", "itemListElement": [{entries}]}}</script>
</head><body></body></html>"""


def product(name, art_id, price=1500):
    """One Product as the site's JSON-LD encodes it."""
    return (f'"{name}"',
            f'"https://www.laanonima.com.ar/{art_id}/art_{art_id}/"',
            f'{{"@type": "Offer", "price": {price}, "priceCurrency": "ARS"}}')


GALLETITAS_URL = "https://www.laanonima.com.ar/galletitas-dulces/n3_598/"


def make_ctx(session, repository, *, stop_event=None, browser_factory=None):
    messages: list[str] = []
    ctx = ScrapeContext(
        slug=ScraperLaAnonima.slug, label=ScraperLaAnonima.label,
        category="almacen", stop_event=stop_event or threading.Event(),
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
    assert ScraperLaAnonima.categories == ("almacen",)


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
    ctx, _messages = make_ctx(session, repository, stop_event=stop_event)

    ScraperLaAnonima().run(ctx)

    assert session.urls == [ALMACEN_URL, DESAYUNO_URL]


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


def _set_event():
    event = threading.Event()
    event.set()
    return event
