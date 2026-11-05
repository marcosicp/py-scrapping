"""SuperMami scraper: Oracle Endeca, the whole category in offset windows.

Measured on 2026-11-05 against ``www.supermami.com.ar`` with the shared
session of ``api/scrapers/http.py``: SuperMami is **not** VTEX (the catalog
API answers 403 and ``/supermami-almacen`` 404); the real platform is Oracle
Endeca, whose category pages (``/super/categoria/<slug>/_/N-<id>``) carry the
products in an embedded ``gtag('event', 'view_item_list', {...})`` script and
the category total in ``Resultado ... de <strong>N</strong>`` — with no
offset ceiling (``No=3200&Nrpp=500`` still answered 200). ``almacen`` totals
3 210 products, and its 15 level-2 children sum only 2 680, so the parent —
not the children — is the collection scope.

The category is resolved from the site menu at run time (``/super/home``
links ``supermami-<categoria>`` to its Endeca path), never from a hardcoded
id or filter string, and each page is read through
``?No=<offset>&Nrpp=500`` until the reported total is reached.
"""

from __future__ import annotations

import json
import math
import re

from bs4 import BeautifulSoup

from api.helpers import name_parse
from api.scrapers.base import BaseScraper, ScrapeContext

BASE_URL = "https://www.supermami.com.ar"
MENU_URL = f"{BASE_URL}/super/home"

# 3 210 products take 7 requests instead of 90 at the legacy 36 per page
# (measured: ``Nrpp=1000`` answered 200 too, but 500 keeps the body sane).
PAGE_SIZE = 500
PAGE_SLEEP_SECONDS = 1

# Transient-failure retries, the policy the Disco run established (D-7):
# one 500 killed a full live run that the next run completed, so page
# requests attempt three times with 2 s / 4 s backoff through ``ctx.sleep``
# (stop-aware, so tests never sleep).
ATTEMPTS = 3
BACKOFF_SECONDS = (2, 4)

TIMEOUT = 90  # the big pages reach tens of MB at ``Nrpp=1000``

# The page's own total, scoped to the measured sentence shape:
# ``Resultado <strong>1</strong> a <strong>500</strong> de <strong>3210</strong>``
# (tolerating whitespace/newlines between the tags). Scoping matters: a
# bare ``de <strong>N</strong>`` matched any such pair in the whole HTML,
# so a word ending in ``de`` followed by a bold number (``verde
# <strong>3</strong>`` — measured to sit before the real sentence today)
# could bind a smaller total, stop the walk after one window and keep the
# gap guard silent.
TOTAL_RE = re.compile(
    r"Resultado\s*<strong>\s*(\d+)\s*</strong>\s*a\s*<strong>\s*\d+\s*"
    r"</strong>\s*de\s*<strong>\s*(\d+)\s*</strong>")

# The Endeca category path, measured live on /super/home:
# ``/super/categoria/<segment>/_/N-<id>``. The <segment> must equal
# ``supermami-<categoria>`` exactly: children and grandchildren share the
# prefix (``supermami-almacen-aceites-vinagres-y-acetos-aceites``) and must
# never match — the declared match captures the path up to and including
# the ``N-<id>``, without any query string.
CATEGORY_PATH_RE = re.compile(
    r"/super/categoria/([A-Za-z0-9-]+)/_/N-([A-Za-z0-9]+)")

CATEGORY_VIEW = "view_item_list"


def _gtag_payload(html: str) -> dict | None:
    """The JSON object of the page's ``view_item_list`` gtag call.

    The object is extracted by brace matching from the first ``{`` after the
    marker — honoring JSON string state — and decoded with ``json.loads``;
    the legacy ``...[:-2]`` text slicing is never reproduced. Returns None
    when the marker is absent or the object does not parse.
    """
    marker = html.find(CATEGORY_VIEW)
    if marker == -1:
        return None
    start = html.find("{", marker)
    if start == -1:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(html)):
        char = html[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    payload = json.loads(html[start:index + 1])
                except ValueError:
                    return None
                return payload if isinstance(payload, dict) else None
    return None


class ScraperSuperMami(BaseScraper):
    """Scrapes SuperMami's categories through Oracle Endeca, browser-free."""

    slug = "supermami"
    label = "SuperMami"
    categories = ("almacen",)

    def run(self, ctx: ScrapeContext) -> None:
        # A stop requested before the run touches the network keeps it inert
        # (the shared pre-cancelled contract guard).
        if ctx.should_stop():
            return
        # One menu per run (an instance attribute, never a class cache).
        self._menu = None

        category = self.validate_category(ctx.category)
        categories = (category,) if category is not None else self.categories

        for categoria in categories:
            if ctx.should_stop():
                break
            ctx.report(f"Scrapeando categoria: {categoria}")
            path = self._discover_category(ctx, categoria)

            documents = self._collect(ctx, path, categoria)
            if documents:
                ctx.save(documents, categoria=categoria)

        ctx.report("PROCESO DETENIDO" if ctx.should_stop()
                   else "PROCESO TERMINADO")

    # -- menu discovery ---------------------------------------------------------

    def _fetch_menu(self, ctx: ScrapeContext) -> str:
        """The menu HTML, fetched at most once per run.

        A discovery outage is fatal on purpose: reporting it as "category
        missing" would end the run as a success with zero products and
        leave a stale slice behind.
        """
        if getattr(self, "_menu", None) is not None:
            return self._menu
        try:
            response = ctx.http.get(MENU_URL, timeout=TIMEOUT)
        except Exception as exc:
            ctx.report(f"Error de red al leer el menú de categorías: {exc}")
            raise
        status = getattr(response, "status_code", None)
        if status != 200:
            ctx.report(f"Error {status} al leer el menú de categorías")
            raise RuntimeError(f"the category menu answered {status}")
        self._menu = response.text
        return self._menu

    def _discover_category(self, ctx: ScrapeContext, categoria: str) -> str:
        """The Endeca path of ``supermami-<categoria>``, fatal otherwise.

        Measured live on ``/super/home``: the parent category has no
        ``href`` at all — its path lives only inside an anchor's
        ``onclick`` (``javascript:getPageCategory('/super/categoria/
        supermami-almacen/_/N-1tjm8rd', '', event);``) — while every
        ``href`` containing ``supermami-almacen`` belongs to a child or a
        grandchild, which come first in document order. So candidates are
        read from both attributes and the category segment must match
        ``supermami-<categoria>`` exactly; a substring test resolves
        ``almacen`` to the first child's Endeca id (75 products) and
        reports success.

        Failures are loud, never a silent skip: a body with links but no
        ``/super/categoria/`` path anywhere (bot wall, error page) is an
        outage, and a valid menu that no longer lists a **declared**
        category means the scraper is broken — both are reported and
        raised instead of ending the run as a success with a stale saved
        slice.
        """
        anchors = BeautifulSoup(self._fetch_menu(ctx),
                               "html.parser").find_all("a")
        if not anchors:
            # Not a menu at all (an error page, a bot wall): an outage,
            # never "zero categories".
            ctx.report("Menú inválido: el HTML no contiene enlaces")
            raise RuntimeError("the menu HTML contains no category links")
        marker = f"supermami-{categoria}"
        has_category_paths = False
        for anchor in anchors:
            for candidate in (anchor.get("href") or "",
                              anchor.get("onclick") or ""):
                found = CATEGORY_PATH_RE.search(candidate)
                if found and found.group(1) == marker:
                    # The path up to and including the ``N-<id>`` segment,
                    # without any query string.
                    return found.group(0)
                has_category_paths = has_category_paths or found is not None
        if not has_category_paths:
            ctx.report("Menú inválido: el HTML no contiene enlaces de "
                       "categorías")
            raise RuntimeError("the menu HTML contains no category links")
        ctx.report(f"No se encontró la categoría {categoria} "
                   f"en el menú de categorías")
        raise RuntimeError(f"the menu lists no {categoria} category")

    # -- collection -----------------------------------------------------------

    def _collect(self, ctx: ScrapeContext, path: str, categoria: str
                 ) -> list[dict]:
        """The whole parent category, paged by ``Nrpp=500`` offsets.

        The parent is the scope on purpose: ``almacen``'s 15 level-2
        children sum 2 680 while the parent reports 3 210, so descending
        would silently lose those 530. ``seen`` keys ``item_id`` across
        every page (Endeca may reprint a product between requests), and an
        incomplete walk is reported with the exact missing count — never
        trimmed silently. The slice is stored name-sorted, the order the
        baseline saved.
        """
        documents: list[dict] = []
        seen: set[str] = set()

        total: int | None = None
        pages = 0
        start = 0
        while (total is None or start < total) and not ctx.should_stop():
            if total is not None:
                ctx.report(f"página {start // PAGE_SIZE + 1}/{pages}")
            page = self._fetch_page(ctx, path, start, categoria,
                                    need_total=total is None)
            if page is None:
                # The stop ended a backoff: nothing is pending, but what the
                # walk collected stays below the guard of this same loop.
                break
            items, page_total = page
            if total is None:
                total = page_total
                pages = max(1, math.ceil(total / PAGE_SIZE))
                ctx.report(f"Total de productos en {categoria}: {total}")
                if total:
                    ctx.report(f"página 1/{pages}")
            for entry in items:
                document = self._to_document(entry)
                if document is None:
                    continue
                identity = document["sku"] or document["name"]
                if identity in seen:
                    continue
                seen.add(identity)
                documents.append(document)
            if not items:
                # An empty window inside the total ends the walk; the gap is
                # measured below, against the total the page itself reports.
                break
            start += PAGE_SIZE
            if start < total and ctx.sleep(PAGE_SLEEP_SECONDS):
                break

        if total is not None and len(documents) < total:
            ctx.report(f"{categoria}: {total - len(documents)} productos "
                       f"faltantes (total {total}, recolectados "
                       f"{len(documents)})")
        # The baseline stored the slice name-sorted; keep that order.
        documents.sort(key=lambda doc: doc["name"])
        return documents

    def _fetch_page(self, ctx: ScrapeContext, path: str, start: int,
                    categoria: str, need_total: bool
                    ) -> tuple[list, int | None] | None:
        """One Endeca window, retried on transient failures.

        Network errors, HTTP >= 500 and a missing/unparsable payload get the
        Disco policy (three attempts, 2 s / 4 s backoff through
        ``ctx.sleep``); a 4xx means the request is wrong and fails on the
        first attempt. After the last attempt the failure is reported once
        and re-raised. A stop requested during a backoff returns ``None`` so
        the walk stops cleanly instead of failing a stopped run.
        """
        url = f"{BASE_URL}{path}?No={start}&Nrpp={PAGE_SIZE}"
        label = f"la página {start // PAGE_SIZE + 1} de {categoria}"
        last_error: Exception | None = None
        last_status: int | None = None
        payload_missing = False
        for attempt in range(ATTEMPTS):
            if attempt > 0 and ctx.sleep(BACKOFF_SECONDS[attempt - 1]):
                return None
            try:
                response = ctx.http.get(url, timeout=TIMEOUT)
            except Exception as exc:
                last_error, last_status = exc, None
                payload_missing = False
                continue
            status = getattr(response, "status_code", None)
            if status != 200:
                if status is not None and status < 500:
                    # 4xx: the request is wrong, not the server.
                    ctx.report(f"Error {status} en {label}")
                    raise RuntimeError(
                        f"the category page answered {status}")
                last_error, last_status = None, status
                payload_missing = False
                continue
            payload = _gtag_payload(response.text)
            if payload is None:
                last_error, last_status = None, None
                payload_missing = True
                continue
            total = None
            if need_total:
                total = self._total_of(response)
                if total is None:
                    # Without the page's own total there is no paging bound:
                    # complete coverage means failing loudly, not paging
                    # blind and trimming silently.
                    ctx.report(f"Respuesta sin total en {categoria}")
                    raise RuntimeError("the page reports no total")
            items = payload.get("items")
            if not isinstance(items, list):
                items = []
            return items, total

        if last_status is not None:
            ctx.report(f"Error {last_status} en {label}")
            raise RuntimeError(f"the category page answered {last_status}")
        if last_error is not None:
            ctx.report(f"Error de red en {label}: {last_error}")
            raise last_error  # type: ignore[misc]  # set whenever status is None
        ctx.report(f"Respuesta sin datos en {label}")
        raise RuntimeError(
            f"the page carries no {CATEGORY_VIEW} payload ({url})")

    @staticmethod
    def _total_of(response) -> int | None:
        """The category total: the number after ``de`` inside the measured
        ``Resultado <strong>1</strong> a <strong>N</strong> de
        <strong>M</strong>`` sentence, never a foreign ``de <strong>…``
        pair."""
        found = TOTAL_RE.search(getattr(response, "text", "") or "")
        return int(found.group(2)) if found else None

    # -- document shape ---------------------------------------------------------

    def _to_document(self, entry: dict) -> dict | None:
        """One stored product document, or None when it has no name."""
        name = entry.get("item_name") if isinstance(entry, dict) else None
        if not isinstance(name, str) or not name.strip():
            return None
        parsed = name_parse(name)
        return {
            "supermercado": self.label,
            "name": parsed["name"],
            "unidad": parsed["unidad"],
            "brand": entry.get("item_brand") or "",
            # Identity is ``item_id`` (``prod...``), stored as ``sku``: the
            # legacy stored no identity at all.
            "sku": str(entry.get("item_id") or ""),
            "price": self._price_of(entry),
            # The site's own leaf label stays with the product while the
            # whole category is saved as one slice (no ``subcategoria``
            # argument to ``ctx.save``).
            "subcategoria": entry.get("item_category") or "",
        }

    @staticmethod
    def _price_of(entry: dict):
        """``price``, or 0 when absent or non-numeric (measured: no ``0``
        prices on SuperMami, but the field is optional in the payload).
        Numeric strings carry a real price and are parsed, not zeroed —
        zeroing is for genuinely non-numeric values (the baseline stored
        whatever the payload carried, never a wrong 0)."""
        price = entry.get("price")
        if isinstance(price, bool):
            return 0
        if isinstance(price, (int, float)):
            return price
        if isinstance(price, str):
            try:
                return float(price)
            except ValueError:
                return 0
        return 0
