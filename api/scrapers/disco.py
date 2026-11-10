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
answers 206, ``_from=2500&_to=2550`` and ``_from=2501`` answer 400.

**Collection scope is the available subset (D-3, owner decision 2026-11-05).**
A price comparer needs what the storefront shows: available offers. Measured
live on ``aceites-y-vinagres`` (1 478 catalog entries): 200 available with a
real price — the only ones ``fq=P:[0.01 TO ...]`` returns — 928 out of stock
with a stale, unusable price (``Price`` 8.69 / 864.29 against ``ListPrice``
718 / 71 429) and 350 out of stock with ``Price 0``. So the filter selects the
*available* subset, not merely products with a price: most of the omitted
entries do carry a price, a stale one. The out-of-stock rows also form one
atomic cluster no price range can split (``fq=P:[0 TO 0]`` alone holds 5 467
on ``golosinas-y-chocolates``), and the storefront the legacy scraper read hid
them — storing those stale/zero prices would be a regression, not a gain.
Every collection request is scoped with ``fq=P:[0.01 TO <priced max>]``, which
indexes available offers only, the exact count of omitted out-of-stock
entries is reported per child ("``sin stock omitidos``", D-7), and the
coverage target is the priced total, not the catalog total. The saved set
therefore matches what the storefront shows: ``almacen``'s 39 220 catalog
entries yield 34 517 out-of-stock entries omitted.

**The range's bounds are never inferred from ``OrderByPriceASC`` (D-3a).**
The first implementation bisected the unfiltered ``ASC``/``DESC`` prices; the
live run proved ``ASC`` does not return the true minimum (479.0 on
``golosinas`` while the out-of-stock atom sat below it, collecting 741 of
6 210), so the lower bound is the constant ``PRICE_FLOOR = 0.01`` and the
upper bound is the ``OrderByPriceDESC`` price fetched *inside* the priced
filter — the real maximum (105 500.0 on ``almacen``). A node whose priced
subset exceeds ``MAX_WINDOW = 2550`` is bisected with ``fq=P:[lo TO hi]``
until every bucket fits; bucket bounds stay inclusive on both ends, so a
boundary product shows up in two buckets and the ``productId`` dedupe absorbs
it (D-4) — the legacy name-substring guard dropped distinct products and is
gone.

**Transient search failures are retried (owner decision 2026-11-05).** A full
live run of ``almacen`` died at 93 s with a 500 and the next run with the same
code and data completed, so ``_search`` retries once (2 s backoff) and twice
(4 s backoff) — through ``ctx.sleep``, so a requested stop is honoured — on
network errors and HTTP >= 500, never on 4xx (the request is wrong, not the
server). Anything else propagates as before (D-9): a discovery outage is
fatal and never looks like "zero subcategories" (D-6), and after the last
attempt the failure is reported and re-raised. A stop requested during a
backoff is not a failure: the explorer loop ends cleanly as ``PROCESO
DETENIDO`` with whatever was already collected.

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
# &_to=2550`` → 400); a bigger priced subset is split by price first.
MAX_WINDOW = 2550
PAGE_SLEEP_SECONDS = 1

# Collection scope (D-3): the out-of-stock cluster (stale prices and
# ``Price 0`` rows, all ``IsAvailable: false``) is atomic and intentionally
# omitted. Every collection request filters on
# ``fq=P:[PRICE_FLOOR TO <priced max>]``, which indexes available offers only.
PRICE_FLOOR = 0.01
# Synthetic scope top, never assumed to hold: the real maximum is measured
# with ``O=OrderByPriceDESC`` inside the priced filter (105 500 on ``almacen``).
PRICE_CEILING = 100_000_000

# Transient-failure retries (owner decision): one 500 killed a full live run
# at 93 s that the next run completed, so search requests -- probes and
# windows alike -- are attempted three times with 2 s / 4 s backoff through
# ``ctx.sleep`` (stop-aware, so tests never sleep).
ATTEMPTS = 3
BACKOFF_SECONDS = (2, 4)

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
        """``(slug, label, search path)`` of the requested category's children.

        Both resolution failures are fatal (R3-002): returning ``[]`` would
        end the run as a success with zero products, so a renamed or removed
        site path would look healthy. The empty-node report differs from the
        missing-node one so the operator can tell them apart.
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
            ctx.report(f"La categoría {categoria} existe en el árbol pero "
                       f"no tiene subcategorías utilizables")
            raise RuntimeError(
                f"the category {categoria} has no usable subcategories in "
                f"the category tree")
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
        """The available subset of one level-two category (D-3, D-3a).

        The out-of-stock atom is a decision to omit, never a silence: its
        exact count is reported per child, and the end-of-child gap is
        measured against the priced total, not the catalog total (D-7). A
        stop reached through a backoff returns without the totals and stops
        cleanly instead of failing.
        """
        documents: list[dict] = []
        seen: set[str] = set()

        total = self._fetch_total(ctx, path, label)
        if not total:
            return documents
        priced = self._fetch_total(ctx, path, label,
                                   (PRICE_FLOOR, PRICE_CEILING))
        if priced is None:
            # The stop hit a backoff: no totals are pending, stop cleanly.
            return documents
        if total > priced:
            ctx.report(f"{label}: {total - priced} sin stock omitidos")
        if not priced:
            return documents

        if priced <= MAX_WINDOW:
            self._page_range(ctx, path, label, (PRICE_FLOOR, PRICE_CEILING),
                             seen, documents, priced)
        else:
            buckets = self._partition_by_price(ctx, path, label)
            for lo, hi, bucket_total in buckets:
                if ctx.should_stop():
                    break
                self._page_range(ctx, path, label, (lo, hi), seen, documents,
                                 min(bucket_total, MAX_WINDOW))

        missing = priced - len(seen)
        if missing > 0:
            ctx.report(f"{label}: {missing} productos faltantes "
                       f"(con precio {priced}, recolectados {len(seen)})")
        return documents

    def _search(self, ctx: ScrapeContext, query_suffix: str, label: str):
        """One GET to the search endpoint, retried on transient failures.

        Network errors and HTTP >= 500 (measured live: a 500 killed a full
        run that the next run completed) get two retries with a 2 s / 4 s
        backoff through ``ctx.sleep``; a 4xx means the request is wrong and
        is reported and raised on the first attempt. After the last attempt
        the failure is reported and re-raised (D-9). A stop requested during
        a backoff returns ``None`` so the callers stop cleanly instead of
        failing a stopped run.
        """
        url = f"{SEARCH_URL}/{query_suffix}"
        last_error: Exception | None = None
        last_status: int | None = None
        for attempt in range(ATTEMPTS):
            if attempt > 0 and ctx.sleep(BACKOFF_SECONDS[attempt - 1]):
                return None
            try:
                response = ctx.http.get(url, timeout=WINDOW_TIMEOUT)
            except Exception as exc:
                last_error, last_status = exc, None
            else:
                status = getattr(response, "status_code", None)
                if status in (200, 206):
                    return response
                if status is not None and status < 500:
                    # 4xx: the request is wrong, not the server.
                    ctx.report(f"Error {status} en {label}")
                    raise RuntimeError(
                        f"the search API answered {status}")
                last_error, last_status = None, status
        if last_status is not None:
            ctx.report(f"Error {last_status} en {label}")
            raise RuntimeError(f"the search API answered {last_status}")
        ctx.report(f"Error de red en {label}: {last_error}")
        raise last_error  # type: ignore[misc]  # set whenever status is None

    def _search_json(self, ctx: ScrapeContext, query_suffix: str,
                     label: str) -> list | None:
        """``_search`` decoded; an invalid body is fatal, like a page error.

        ``None`` means the stop ended a backoff with no response available.
        """
        response = self._search(ctx, query_suffix, label)
        if response is None:
            return None
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
        if response is None:
            return None
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
        """Bisect the priced subset (D-3, D-3a).

        The range starts at ``PRICE_FLOOR`` — never at an ``OrderByPriceASC``
        value — and its top is the measured priced maximum. Returns the
        finalized ``[lo, hi]`` buckets (each with its measured total) in
        detection order, every one at or under ``MAX_WINDOW``. Bucket bounds
        stay inclusive on both ends, as the API is.
        """
        high = self._priced_max(ctx, path, label)
        final_buckets: list[tuple[float, float, int]] = []
        queue: list[tuple[float, float]] = [(PRICE_FLOOR, high)]
        while queue:
            lo, hi = queue.pop(0)
            if ctx.should_stop():
                break
            total = self._fetch_total(ctx, path, label, price_range=(lo, hi))
            if total is None:
                # The stop hit a backoff: stop cleanly, keep what is finalized.
                break
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

    def _priced_max(self, ctx: ScrapeContext, path: str, label: str) -> float:
        """The true maximum of the priced subset (D-3a).

        ``O=OrderByPriceDESC`` measured *inside* the priced filter. The ASC
        direction is deliberately never used as a bound helper: its
        unfiltered first window returned 479.0 live on ``golosinas`` while
        the out-of-stock atom sat below it, and a lower bound may not be
        inferred from a sort.
        """
        items = self._search_json(
            ctx, f"{path}?_from=0&_to=0&O=OrderByPriceDESC"
                 f"&fq=P:[{PRICE_FLOOR} TO {PRICE_CEILING}]", label)
        if items is None:
            return PRICE_FLOOR
        if not items or not isinstance(items[0], dict):
            return PRICE_FLOOR
        price = self._price_of(items[0])
        if not isinstance(price, (int, float)) or isinstance(price, bool):
            return PRICE_FLOOR
        return max(float(price), PRICE_FLOOR)

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
