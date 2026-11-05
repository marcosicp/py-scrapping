"""Disco scraper: the VTEX catalog API (replaces the browser + json-LD path).

Measured on 2026-11-05 against ``www.disco.com.ar`` with the shared session of
``api/scrapers/http.py``: the category tree
(``/api/catalog_system/pub/category/tree/2``, 200) and the search endpoint
(``/api/catalog_system/pub/products/search/<path>?_from=0&_to=2`` → 206 with
``resources: 0-2/1478``) answer everything the HTML path scraped, so the Chrome
driver, the scroll, the CSS-class total and the BeautifulSoup parse go away
(D-1). Children are matched by URL path under the requested category with the
slug as the last path segment — Carrefour's ``_discover_subcategories`` (D-2).

The search API caps every offset window at 2550 items: ``_from=2500&_to=2549``
answers 206, ``_from=2500&_to=2550`` and ``_from=2501`` answer 400. Nodes
bigger than that (``desayuno-y-merienda`` holds 13 317 products) cannot be
paged flat and their level-3 children do not partition them exactly, so an
oversized node is measured (min/max price via ``O=OrderByPriceASC/DESC``) and
bisected with ``fq=P:[lo TO hi]`` until every bucket fits the ceiling; bucket
bounds are inclusive on both ends, so a boundary product shows up in two
buckets and the ``productId`` dedupe absorbs it (D-3). Identity is
``productId`` — the legacy name-substring guard dropped distinct products
(D-4).

Every saved slice is ``categoria=<requested category>``,
``subcategoria=<child slug>`` (D-5): no Disco documents exist in
``lalistitadev.productos`` today, so nothing needs migrating.

Discovery outages are fatal and never look like "zero subcategories" (D-6),
page failures propagate without retries (D-9), and an incomplete collection is
always reported with the exact missing count — never trimmed silently (D-7).
"""

from __future__ import annotations

from urllib.parse import urlsplit

from api.helpers import name_parse
from api.scrapers.base import BaseScraper, ScrapeContext

BASE_URL = "https://www.disco.com.ar"
TREE_URL = f"{BASE_URL}/api/catalog_system/pub/category/tree/2"
SEARCH_URL = f"{BASE_URL}/api/catalog_system/pub/products/search"

PAGE_SIZE = 50
# The search API rejects any window beyond item 2549 (measured: ``_from=2500
# &_to=2550`` → 400); a node bigger than this is split by price first.
MAX_WINDOW = 2550
PAGE_SLEEP_SECONDS = 1

TREE_TIMEOUT = 30      # the tree is one 211 KB request per run
WINDOW_TIMEOUT = 90    # ~31 KB per product: a 50-item page reaches ~1.6 MB


def _path_of(url: str) -> str:
    """The URL path without its trailing slash, e.g. ``/almacen/snacks``."""
    return urlsplit(url or "").path.rstrip("/")


def _slug_of(url: str) -> str:
    """The last path segment of a category URL, e.g. ``snacks``."""
    return _path_of(url).rsplit("/", 1)[-1]


class ScraperDisco(BaseScraper):
    """Scrapes Disco's categories through the VTEX catalog API."""

    slug = "disco"
    label = "Disco"
    categories = ("almacen",)

    def run(self, ctx: ScrapeContext) -> None:
        # A stop requested before the run touches the network keeps it inert
        # (the shared pre-cancelled contract guard).
        if ctx.should_stop():
            return
        # One tree per run (an instance attribute, never a class cache).
        self._tree = None

        category = self.validate_category(ctx.category)
        categories = (category,) if category is not None else self.categories

        for categoria in categories:
            if ctx.should_stop():
                break
            ctx.report(f"Scrapeando categoria: {categoria}")
            subcategorias = self._discover_subcategories(ctx, categoria)
            if not subcategorias:
                ctx.report(f"No se encontraron subcategorías de {categoria} "
                           f"en el árbol de categorías")
                continue

            ctx.report(f"Subcategorías encontradas en {categoria}: "
                       f"{len(subcategorias)}")
            for slug, label, path in subcategorias:
                if ctx.should_stop():
                    break
                ctx.report(f"Subcategoría: {label}")
                documents = self._collect(ctx, path, label)
                if documents:
                    ctx.save(documents, categoria=categoria,
                             subcategoria=slug)

        ctx.report("PROCESO DETENIDO" if ctx.should_stop()
                   else "PROCESO TERMINADO")

    # -- category tree -------------------------------------------------------

    def _fetch_tree(self, ctx: ScrapeContext):
        """The catalog tree, fetched at most once per run.

        A discovery outage is fatal on purpose (R3-001 via D-6): reporting it
        as "no subcategories" would end the run as a success with zero
        products and leave a stale slice in the database.
        """
        if getattr(self, "_tree", None) is not None:
            return self._tree
        try:
            response = ctx.http.get(TREE_URL, timeout=TREE_TIMEOUT)
        except Exception as exc:
            ctx.report(f"Error de red al leer el árbol de categorías: {exc}")
            raise
        if response.status_code != 200:
            ctx.report(f"Error {response.status_code} al leer el árbol de "
                       f"categorías")
            raise RuntimeError(
                f"the category tree answered {response.status_code}")
        try:
            self._tree = response.json()
        except Exception as exc:
            ctx.report(f"Árbol de categorías inválido: {exc}")
            raise RuntimeError("the category tree is not valid JSON") from exc
        return self._tree

    def _discover_subcategories(self, ctx: ScrapeContext, categoria: str
                                ) -> list[tuple[str, str, str]]:
        """``(slug, label, search path)`` of the requested category's children."""
        tree = self._fetch_tree(ctx)
        if tree is None:
            return []

        node = self._category_node(tree, categoria)
        if node is None:
            return []

        subcategories: list[tuple[str, str, str]] = []
        seen: set[str] = set()
        for child in node.get("children") or []:
            if not isinstance(child, dict):
                continue
            slug = _slug_of(child.get("url") or "")
            if not slug or slug in seen:
                continue
            seen.add(slug)
            subcategories.append((slug, child.get("name") or slug,
                                  f"{categoria}/{slug}"))
        return subcategories

    @staticmethod
    def _category_node(nodes, categoria: str):
        """The tree node whose path is exactly ``/<categoria>``, or None."""
        expected = f"/{categoria}"
        for node in nodes or []:
            if not isinstance(node, dict):
                continue
            if _path_of(node.get("url") or "") == expected:
                return node
            found = ScraperDisco._category_node(node.get("children"),
                                                categoria)
            if found is not None:
                return found
        return None

    # -- collection ----------------------------------------------------------

    def _collect(self, ctx: ScrapeContext, path: str, label: str
                 ) -> list[dict]:
        """Every reachable product of one level-two category.

        An incomplete collection is never silent (D-7): the difference with
        the total the API reported is reported with the exact count, whatever
        produced it (a ``P`` bucket that under-indexes, a bisection that
        cannot split further ...).
        """
        documents: list[dict] = []
        seen: set[str] = set()

        total = self._fetch_total(ctx, path, label)
        if not total:
            return documents

        if total <= MAX_WINDOW:
            self._page_range(ctx, path, label, None, seen, documents, total)
        else:
            buckets = self._partition_by_price(ctx, path, label)
            for lo, hi, bucket_total in buckets:
                if ctx.should_stop():
                    break
                self._page_range(ctx, path, label, (lo, hi), seen, documents,
                                 min(bucket_total, MAX_WINDOW))

        missing = total - len(seen)
        if missing > 0:
            ctx.report(f"{label}: {missing} productos faltantes "
                       f"(total del catálogo {total}, "
                       f"recolectados {len(seen)})")
        return documents

    def _search(self, ctx: ScrapeContext, query_suffix: str, label: str):
        """One GET to the search endpoint.

        Page failures are fatal (D-9): they propagate and never retry, and
        the children already saved keep their fresh data.
        """
        url = f"{SEARCH_URL}/{query_suffix}"
        try:
            response = ctx.http.get(url, timeout=WINDOW_TIMEOUT)
        except Exception as exc:
            ctx.report(f"Error de red en {label}: {exc}")
            raise
        if response.status_code not in (200, 206):
            ctx.report(f"Error {response.status_code} en {label}")
            raise RuntimeError(
                f"the search API answered {response.status_code}")
        return response

    def _search_json(self, ctx: ScrapeContext, query_suffix: str,
                     label: str) -> list:
        """``_search`` decoded; an invalid body is fatal, like a page error."""
        response = self._search(ctx, query_suffix, label)
        try:
            return response.json() or []
        except Exception as exc:
            ctx.report(f"Respuesta inválida en {label}: {exc}")
            raise RuntimeError("the search response is not valid JSON") \
                from exc

    @staticmethod
    def _total_from(response) -> int | None:
        """The catalog total from the ``resources: from-to/total`` header."""
        headers = getattr(response, "headers", None)
        if headers is None:
            return None
        raw = None
        if hasattr(headers, "get"):
            raw = headers.get("resources") or headers.get("Resources")
        if not raw:
            return None
        try:
            return int(str(raw).rsplit("/", 1)[-1])
        except (TypeError, ValueError):
            return None

    def _fetch_total(self, ctx: ScrapeContext, path: str, label: str,
                     price_range: tuple[float, float] | None = None
                     ) -> int | None:
        """The node (or bucket) total, from the ``_from=0&_to=0`` probe."""
        query = "_from=0&_to=0"
        if price_range:
            lo, hi = price_range
            query = f"{query}&fq=P:[{lo} TO {hi}]"
        response = self._search(ctx, f"{path}?{query}", label)
        total = self._total_from(response)
        if total is None:
            # Without the header there is no reliable paging bound: complete
            # coverage (D-7) means failing loudly, not paging blind and
            # trimming silently.
            ctx.report(f"Respuesta sin total en {label}")
            raise RuntimeError("the search response has no resources total")
        return total

    # -- price partition (the 2550 ceiling) ----------------------------------

    def _partition_by_price(self, ctx: ScrapeContext, path: str, label: str
                            ) -> list[tuple[float, float, int]]:
        """Bisect the node's measured price range (D-3).

        Returns the finalized ``[lo, hi]`` buckets (each with its measured
        total) in detection order, every one at or under ``MAX_WINDOW``.
        Bucket bounds stay inclusive on both ends, as the API is.
        """
        low = self._price_bound(ctx, path, label, "OrderByPriceASC")
        high = self._price_bound(ctx, path, label, "OrderByPriceDESC")
        final_buckets: list[tuple[float, float, int]] = []
        queue: list[tuple[float, float]] = [(low, high)]
        while queue:
            lo, hi = queue.pop(0)
            if ctx.should_stop():
                break
            total = self._fetch_total(ctx, path, label, price_range=(lo, hi))
            if not total:
                continue
            if total <= MAX_WINDOW:
                final_buckets.append((lo, hi, total))
                continue
            mid = (lo + hi) / 2
            if mid <= lo or mid >= hi:
                # Float resolution reached (or one single price): the bucket
                # cannot split. Keep it, page only its reachable window; the
                # child-end gap report names the exact remainder (D-7).
                final_buckets.append((lo, hi, total))
                continue
            queue.append((lo, mid))
            queue.append((mid, hi))
        return final_buckets

    def _price_bound(self, ctx: ScrapeContext, path: str, label: str,
                     order: str) -> float:
        """The single ``O={order}`` window's price: min (ASC) or max (DESC)."""
        items = self._search_json(
            ctx, f"{path}?_from=0&_to=0&O={order}", label)
        if not items or not isinstance(items[0], dict):
            return 0.0
        return float(self._price_of(items[0]) or 0.0)

    # -- paging ----------------------------------------------------------------

    def _page_range(self, ctx: ScrapeContext, path: str, label: str,
                    price_range: tuple[float, float] | None,
                    seen: set[str], documents: list[dict], cap: int) -> None:
        """Page ``[0, cap)`` of a node (or a price bucket) into ``documents``.

        ``seen`` is the per-child dedupe (D-4): shared across every window
        and bucket of a child, key ``str(productId)``.
        """
        start = 0
        while start < cap and not ctx.should_stop():
            query = f"_from={start}&_to={start + PAGE_SIZE - 1}"
            if price_range:
                lo, hi = price_range
                query = f"{query}&fq=P:[{lo} TO {hi}]"
            items = self._search_json(ctx, f"{path}?{query}", label)
            if not items:
                break

            for item in items:
                document = self._to_document(item)
                if document is None:
                    continue
                identity = document["sku"] or document["name"]
                if identity in seen:
                    continue
                seen.add(identity)
                documents.append(document)

            start += PAGE_SIZE
            if start < cap and ctx.sleep(PAGE_SLEEP_SECONDS):
                break

    # -- document shape --------------------------------------------------------

    def _to_document(self, item: dict) -> dict | None:
        """One stored product document, or None when it has no name."""
        name = item.get("productName")
        if not isinstance(name, str) or not name.strip():
            return None

        parsed = name_parse(name)
        return {
            "supermercado": self.label,
            "name": parsed["name"],
            "unidad": parsed["unidad"],
            "brand": item.get("brand") or "",
            # The catalog API carries no ``sku`` key; ``productId`` is the
            # stable identity and the one Carrefour stores today.
            "sku": str(item.get("productId") or ""),
            "price": self._price_of(item),
        }

    @staticmethod
    def _price_of(item: dict):
        """``items[0].sellers[0].commertialOffer.Price``, or 0 when absent."""
        items = item.get("items") or []
        if not items or not isinstance(items[0], dict):
            return 0
        sellers = items[0].get("sellers") or []
        if not sellers or not isinstance(sellers[0], dict):
            return 0
        offer = sellers[0].get("commertialOffer") or {}
        price = offer.get("Price") if isinstance(offer, dict) else None
        if isinstance(price, bool) or not isinstance(price, (int, float)):
            return 0
        return price
