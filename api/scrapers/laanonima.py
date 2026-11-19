"""La Anónima scraper: successor of the HiperLibertad module.

``hiperlibertad.com.ar`` answers 301 to ``laanonima.com.ar`` and the VTEX
search API the legacy module consumed answers 403, so this is a new collector
rather than a port of the old one. Two properties of the site decide the
design:

1. The category tree is rendered into the navigation menu of every category
   page: ``a.menu-n1`` -> ``a.menu-n2`` -> ``a.menu-n3``. Node ids are the
   site's, not ours, so the subcategories are discovered at run time instead
   of hardcoded; a redesign that removes the menu is reported as a failure
   instead of silently saving nothing.
2. Each n2 node page embeds its **whole** product list as a JSON-LD
   ``ItemList`` (name, url with the ``art_<id>`` identity, offers.price in
   ARS). A n2 node already includes its n3 children, so the run walks the n2
   level only: fetching both would duplicate every product.
3. Some n1 categories are **leaves**: the menu carries their ``a.menu-n1``
   anchor but no ``a.menu-n2`` under it — an n1 whose page is the collection
   scope itself (measured 2026-11-21 on such a page: 201 items embedded).
   The leaf's own n1 page embeds the JSON-LD ``ItemList`` too, so it is
   scraped as a single node stored under the category's own slug. "The menu
   no longer lists this category" and "this category has no children" are
   different facts and are never collapsed: the first keeps the loud report
   (W-3 of ``odd/tasks/chain-categories-wave-a.md``), the second is the
   taxonomy's shape (W-2).

No browser is used: plain GET responses through ``ctx.http``. Products are
deduplicated by ``art_<id>``, not by name substring: after ``name_parse``
strips the unit, a substring guard silently drops distinct variants.
"""

from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup

from api.helpers import name_parse
from api.scrapers.base import BaseScraper, ScrapeContext

# https://www.laanonima.com.ar/<node-slug>/n2_<id>/
_NODE_HREF = re.compile(
    r"^https://www\.laanonima\.com\.ar/([a-z0-9-]+)/n2_\d+/?$")
# https://www.laanonima.com.ar/<slug>/art_<id>/
_ART_ID = re.compile(r"/art_(\d+)")


class ScraperLaAnonima(BaseScraper):
    """Scrapes La Anónima's categories through plain HTTP."""

    slug = "laanonima"
    label = "La Anónima"
    # The n1 categories of the whole editable shelf; the node id of each
    # is a site fact (measured 2026-11-21), not something we can derive.
    # ``mascotas`` is no longer declared (comparator-focus F-1): the leaf
    # shape it exercised stays supported and tested, the category can come
    # back later as its own feature.
    categories = ("almacen", "bebidas", "lacteos-y-frescos", "congelados",
                  "frutas-y-verduras", "carniceria", "perfumeria",
                  "limpieza")

    # The node id is part of the site's URL, not something we can derive.
    # Keys must stay exactly the ``categories`` tuple, in the same order.
    CATEGORY_NODES = {
        "almacen": "https://www.laanonima.com.ar/almacen/n1_512/",
        "bebidas": "https://www.laanonima.com.ar/bebidas/n1_513/",
        "lacteos-y-frescos":
            "https://www.laanonima.com.ar/lacteos-y-frescos/n1_516/",
        "congelados": "https://www.laanonima.com.ar/congelados/n1_766/",
        "frutas-y-verduras":
            "https://www.laanonima.com.ar/frutas-y-verduras/n1_517/",
        "carniceria": "https://www.laanonima.com.ar/carniceria/n1_518/",
        "perfumeria": "https://www.laanonima.com.ar/perfumeria/n1_820/",
        "limpieza": "https://www.laanonima.com.ar/limpieza/n1_514/",
    }

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
            node_url = self.CATEGORY_NODES.get(categoria)
            if node_url is None:
                ctx.report(f"Categoría sin nodo configurado: {categoria}")
                continue

            ctx.report(f"Scrapeando categoria: {categoria}")
            subcategorias = self._discover_nodes(ctx, node_url)
            if subcategorias is None:
                # The menu could not be read, or it no longer lists the
                # category (a site change): today's loud report, nothing
                # saved (W-3).
                ctx.report(f"No se encontraron subcategorías de {categoria} "
                           f"en el menú de {node_url}")
                continue
            if not subcategorias:
                # A leaf n1 (W-2): the anchor exists but carries no n2
                # children — the n1 page itself is the collection scope
                # and its own slug is the stored ``subcategoria``.
                ctx.report(f"{categoria} no tiene subcategorías: se scrapea "
                           "la categoría misma")
                subcategorias = [(categoria, categoria, node_url)]
            else:
                ctx.report(f"Subcategorías encontradas: {len(subcategorias)}")

            for slug, label, url in subcategorias:
                if ctx.should_stop():
                    break
                ctx.report(f"Subcategoría: {label}")
                documents = self._scrape_node(ctx, url, slug)
                if documents:
                    ctx.save(documents, categoria=categoria,
                             subcategoria=slug)

        ctx.report("PROCESO DETENIDO" if ctx.should_stop()
                   else "PROCESO TERMINADO")

    def _discover_nodes(self, ctx: ScrapeContext, node_url: str
                        ) -> list[tuple[str, str, str]] | None:
        """The n2 nodes nested under ``node_url`` in the site menu.

        Three facts, never collapsed (W-2/W-3): ``None`` — the menu could
        not be read or the anchor for ``node_url`` is not in it, the site
        change the caller reports loudly; ``[]`` — the anchor exists but
        has no ``menu-n2`` children, a leaf n1 the caller scrapes as a
        single node; otherwise the n2 nodes in menu order.
        """
        try:
            response = ctx.http.get(node_url, timeout=30)
        except Exception as exc:  # network failures must not kill the run
            ctx.report(f"Error de red al leer el menú: {exc}")
            return None
        if response.status_code != 200:
            ctx.report(f"Error {response.status_code} al leer el menú de "
                       f"categorías")
            return None

        soup = BeautifulSoup(response.text, "html.parser")
        anchor = self._category_anchor(soup, node_url)
        if anchor is None:
            return None
        container = anchor.find_parent("li")
        if container is None:
            return None

        nodes: list[tuple[str, str, str]] = []
        seen: set[str] = set()
        for candidate in container.select("a.menu-n2"):
            url = (candidate.get("href") or "").strip()
            match = _NODE_HREF.match(url)
            if match is None or match.group(1) in seen:
                continue
            seen.add(match.group(1))
            nodes.append((match.group(1), candidate.get_text(strip=True), url))
        return nodes

    @staticmethod
    def _category_anchor(soup: BeautifulSoup, node_url: str):
        """The menu anchor for ``node_url``, or None when the menu changed."""
        expected = node_url.rstrip("/")
        for candidate in soup.select("a.menu-n1"):
            if (candidate.get("href") or "").strip().rstrip("/") == expected:
                return candidate
        return None

    def _scrape_node(self, ctx: ScrapeContext, url: str, subcategoria: str
                     ) -> list[dict]:
        """Every product of one n2 node, read from its JSON-LD item list."""
        try:
            response = ctx.http.get(url, timeout=30)
        except Exception as exc:
            ctx.report(f"Error de red en {subcategoria}: {exc}")
            return []
        if response.status_code != 200:
            ctx.report(f"Error {response.status_code} en {subcategoria}")
            return []

        items = self._item_list(response.text)
        if not items:
            ctx.report(f"Sin datos en {subcategoria}")
            return []

        documents: list[dict] = []
        seen: set[str] = set()
        for item in items:
            document = self._to_document(item)
            if document is None:
                continue
            identity = document["sku"] or item.get("url") or document["name"]
            if identity in seen:
                continue
            seen.add(identity)
            documents.append(document)
        return documents

    @staticmethod
    def _item_list(html: str) -> list[dict]:
        """The ``itemListElement`` items of the page's JSON-LD ItemList."""
        soup = BeautifulSoup(html, "html.parser")
        for script in soup.find_all("script",
                                    attrs={"type": "application/ld+json"}):
            raw = script.string if script.string is not None \
                else script.get_text()
            try:
                data = json.loads(raw)
            except (TypeError, ValueError):
                continue
            items = ScraperLaAnonima._items_from(data)
            if items is not None:
                return items
        return []

    @staticmethod
    def _items_from(data) -> list[dict] | None:
        """Products of a decoded JSON-LD document; None when it is not one."""
        if isinstance(data, dict) and data.get("@type") == "ItemList":
            return [entry["item"] for entry in data.get("itemListElement", [])
                    if isinstance(entry, dict) and isinstance(
                        entry.get("item"), dict)]
        if isinstance(data, dict) and isinstance(data.get("@graph"), list):
            for node in data["@graph"]:
                items = ScraperLaAnonima._items_from(node)
                if items is not None:
                    return items
        if isinstance(data, list):
            for node in data:
                items = ScraperLaAnonima._items_from(node)
                if items is not None:
                    return items
        return None

    def _to_document(self, item: dict) -> dict | None:
        """One stored product document, or None when the item has no name."""
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            return None

        parsed = name_parse(name)
        price = (item.get("offers") or {}).get("price") \
            if isinstance(item.get("offers"), dict) else None
        if isinstance(price, bool) or not isinstance(price, (int, float)):
            price = 0
        match = _ART_ID.search(item.get("url") or "")

        return {
            "supermercado": self.label,
            "name": parsed["name"],
            "unidad": parsed["unidad"],
            "brand": "",
            "sku": match.group(1) if match is not None else "",
            "price": price,
        }
