"""Carrefour scraper: the VTEX catalog API (replaces the two HTML paths).

Measured on 2026-11-04: ``/almacen`` answers 200 with 4.7 MB of VTEX HTML and
**no** JSON-LD, while
``/api/catalog_system/pub/products/search/almacen?_from=0&_to=2`` answers 206
with ``resources: 0-2/6188`` and the full product objects as JSON. That header
is the page count, and it is the only reliable total: the HTML total lives in
generated CSS class names (``...-0-x-totalProducts--layout``).

The API refuses ``_from=2501`` with a 400, so a flat crawl of almacén (6188
products) cannot reach the last 1388. The run therefore walks the level-two
categories, read at run time from
``/api/catalog_system/pub/category/tree/2`` and matched by URL path: almacén's
ten children partition the parent exactly (437+694+453+533+1050+1224+207+546+
892+152 = 6188) and the largest holds 1933 products, comfortably below the
ceiling. A new subcategory is picked up without touching this module; the
legacy list of 18 hardcoded slugs is gone.

No browser is used anywhere: both the requested-category path and the
every-category path are plain GETs, so the Chrome driver, the scroll loop and
the ``render-provider`` script are no longer part of this scraper.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from api.helpers import name_parse
from api.scrapers.base import BaseScraper, ScrapeContext

BASE_URL = "https://www.carrefour.com.ar"
TREE_URL = f"{BASE_URL}/api/catalog_system/pub/category/tree/2"
SEARCH_URL = f"{BASE_URL}/api/catalog_system/pub/products/search"

PAGE_SIZE = 50
# The VTEX search API rejects _from=2501 (measured), so no page loop may cross
# 2500 without splitting first.
PAGE_SLEEP_SECONDS = 1


def _path_of(url: str) -> str:
    """The URL path without its trailing slash, e.g. ``/almacen/snacks``."""
    return urlsplit(url or "").path.rstrip("/")


def _slug_of(url: str) -> str:
    """The last path segment of a category URL, e.g. ``snacks``."""
    return _path_of(url).rsplit("/", 1)[-1]


class ScraperCarrefour(BaseScraper):
    """Scrapes Carrefour's categories through the VTEX catalog API."""

    slug = "carrefour"
    label = "Carrefour"
    categories = ("almacen", "desayuno-y-merienda")

    # Fetched once per run: the tree is the whole catalog (166 KB).
    _tree = None

    def run(self, ctx: ScrapeContext) -> None:
        # A stop requested before the run touches the network keeps it inert
        # (the shared pre-cancelled contract guard).
        if ctx.should_stop():
            return

        category = self.validate_category(ctx.category)
        categories = (category,) if category is not None else self.categories

        for categoria in categories:
            if ctx.should_stop():
                break
            ctx.report(f"Scrapeando categoria: {categoria}")
            subcategorias = self._discover_subcategories(ctx, categoria)
            if not subcategorias:
                ctx.report(f"Sin subcategorías que recorrer en {categoria}; "
                           f"se continúa con la siguiente")
                continue

            ctx.report(f"Subcategorías encontradas en {categoria}: "
                       f"{len(subcategorias)}")
            for slug, label, path in subcategorias:
                if ctx.should_stop():
                    break
                ctx.report(f"Subcategoría: {label}")
                documents = self._scrape_subcategory(ctx, categoria, slug, path)
                if documents:
                    ctx.save(documents, categoria=categoria,
                             subcategoria=slug)

        ctx.report("PROCESO DETENIDO" if ctx.should_stop()
                   else "PROCESO TERMINADO")

    # -- category tree -------------------------------------------------------

    def _fetch_tree(self, ctx: ScrapeContext):
        """The catalog tree, fetched at most once per run.

        A discovery outage is fatal on purpose (R3-001): reporting it as "no
        subcategories" would end the run as a success with zero products and
        leave a stale slice in the database, which is exactly what the
        previous browser path did not do (a driver failure propagated).
        """
        if self._tree is not None:
            return self._tree
        try:
            response = ctx.http.get(TREE_URL, timeout=30)
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
        """``(slug, label, search path)`` of the requested category's children.

        A category MISSING from the tree is fatal (R3-002): returning ``[]``
        there would end the run as a success with zero products, so a renamed
        or removed site path would look healthy.

        A category that resolves but has no usable children is reported and
        returns ``[]``: the caller skips it and keeps walking the remaining
        categories. Failing the whole run there would be a regression, because
        one legitimately empty category would block every other one.
        """
        tree = self._fetch_tree(ctx)

        node = self._category_node(tree, categoria)
        if node is None:
            ctx.report(f"La categoría {categoria} no está en el árbol de "
                       f"categorías")
            raise RuntimeError(
                f"the category {categoria} is not in the category tree")

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
        if not subcategories:
            ctx.report(f"La categoría {categoria} existe en el árbol pero no "
                       f"tiene subcategorías utilizables")
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
            found = ScraperCarrefour._category_node(node.get("children"),
                                                    categoria)
            if found is not None:
                return found
        return None

    # -- collection ----------------------------------------------------------

    def _scrape_subcategory(self, ctx: ScrapeContext, categoria: str,
                            subcategoria: str, path: str) -> list[dict]:
        """Every product of one level-two category, paged by ``resources``.

        A page failure is fatal instead of ending the child early (the same
        policy ``changomas.py`` and ``disco.py`` apply): the caller saves
        whatever this returns, and ``replace_products`` REPLACES the slice,
        so returning a truncated list would wipe the stored catalog for this
        subcategory while the run still reported ``PROCESO TERMINADO``.
        Raising leaves the previous slice untouched and marks the run failed.
        """
        documents: list[dict] = []
        seen: set[str] = set()
        start = 0

        while not ctx.should_stop():
            url = (f"{SEARCH_URL}/{path}"
                   f"?_from={start}&_to={start + PAGE_SIZE - 1}")
            try:
                response = ctx.http.get(url, timeout=30)
            except Exception as exc:
                ctx.report(f"Error de red en {subcategoria}: {exc}. "
                           f"No se guarda la recolección parcial")
                raise
            if response.status_code not in (200, 206):
                ctx.report(f"Error {response.status_code} en {subcategoria}. "
                           f"No se guarda la recolección parcial")
                raise RuntimeError(
                    f"the search API answered {response.status_code}")

            try:
                items = response.json() or []
            except Exception as exc:
                ctx.report(f"Respuesta inválida en {subcategoria}: {exc}. "
                           f"No se guarda la recolección parcial")
                raise RuntimeError(
                    f"{subcategoria} answered invalid JSON") from exc
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
            total = self._total_from(response)
            if total is not None and start >= total:
                break
            if ctx.sleep(PAGE_SLEEP_SECONDS):
                break

        return documents

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
            # VTEX search results carry no ``sku`` key; the product id is the
            # stable identity and the one embedded in the product URL.
            "sku": str(item.get("productId") or ""),
            "price": self._price_of(item),
            # The item's EAN barcode as a string, "" when absent or null.
            "ean": self._ean_of(item),
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

    @staticmethod
    def _ean_of(item: dict) -> str:
        """``items[0].ean`` as a string, or "" when absent or null."""
        items = item.get("items") or []
        ean = items[0].get("ean") if items and isinstance(items[0], dict) \
            else None
        return str(ean) if ean else ""
