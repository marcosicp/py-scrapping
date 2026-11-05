# Disco scraper rewrite — VTEX catalog API, complete coverage

**Branch:** `feat/disco-vtex-rewrite` (from `main`)
**Status:** IN PROGRESS — T3 open

Rewrite `api/scrapers/disco.py` with the same techniques that already work for
Carrefour (`carrefour-scraper-rewrite`) and La Anónima (`scrape-admin-view`):
read the site's own category tree at run time, pull products from the
structured catalog endpoint instead of scraping HTML with a browser, deduplicate
by product identity, and save one subcategory at a time.

Requested by the owner: *"tenemos que acomodar el scraper de Disco con las
mismas técnicas que usamos para los otros que ya funcionan."*

---

## 1. What the current scraper does (and why it must change)

`api/scrapers/disco.py` is the mechanical port of the legacy module (T9). It
still:

- drives a **Chrome driver** (`ctx.browser()`) to open each subcategory page,
  scrolls, and reads the total from a generated CSS class;
- pages the **HTML** with `?page=N` and parses the embedded JSON-LD
  `itemListElement` with BeautifulSoup;
- **never collects page 1** (documented quirk, `:108`);
- hardcodes **14 subcategory slugs**;
- deduplicates by **name substring** (`any(element['name'] in name ...)`), which
  drops legitimately distinct products.

Every one of those is either wrong today or unnecessary: the site answers the
VTEX catalog API directly.

## 2. Measurements (2026-11-05, against `www.disco.com.ar`)

All figures were observed with `api/scrapers/http.py`'s shared session, i.e.
the exact request fingerprint the scrapers already use.

| Measurement | Result |
| --- | --- |
| `GET /almacen/aceites-y-vinagres` | 200, 322 KB of HTML |
| `GET /api/catalog_system/pub/products/search/almacen/aceites-y-vinagres?_from=0&_to=2` | **206**, `resources: 0-2/1478`, full product objects as JSON |
| `GET /api/catalog_system/pub/category/tree/2` | 200, 211 KB, full tree |
| `almacen` total | **39 220** products |
| Sum of `almacen`'s **15** level-2 children | **39 220** — exact partition |
| Legacy hardcoded list vs the tree today | 2 slugs gone (`aceitunas-y-encurtidos`, `sin-tacc`), 1 renamed (`caldos-sopas-y-pure` → `caldos-sopas-pure-y-bolsas-para-horno`), 3 missing (`harinas`, `mesa-dulce-navidena`, `cajas-navidenas`) |
| Ceiling: `_from=2500&_to=2549` | 206, 50 items |
| Ceiling: `_from=2500&_to=2550` / `_from=2501` | **400** — the window is capped at 2550 items |
| Children above the ceiling | `desayuno-y-merienda` 13 317, `golosinas-y-chocolates` 6 210 |
| `?page=3&count=50` | ignored (always returns 10 items) — no page-style deep paging |
| `fq=B:OREO` (brand by name) | 400 |
| `fq=B:775` (brand by id) | 206 — brand filter works by id |
| `fq=P:[5000 TO 10000]` (price range) | **206 — price filter works** |
| `O=OrderByPriceASC` / `OrderByPriceDESC` | min 650.0 / max 30 350.0 on `galletitas-dulces` |
| Price buckets `[0,5000] [5000,10000] [10000,30000]` on `galletitas-dulces` | 2882 + 60 + 33 = **2975 vs a real total of 2974** → bounds are inclusive on both ends; duplicates are expected and dedupe by id absorbs them |
| Level-3 children of `desayuno-y-merienda` | 12 children summing **13 285** vs the parent's 13 317 → descending does **not** partition exactly (32 products unreachable that way) |
| `galletitas-dulces` (a level-3 leaf) | 2 974 — above the ceiling and childless |
| Payload size | ~31 KB per product (~1.5 MB per 50-item page) |

## 3. Decisions

**D-1 — Read the catalog API, not the HTML. Drop the browser entirely.**
Both the tree and the search endpoint are plain GETs, so the Chrome driver,
the scroll, the class-name total and the BeautifulSoup parse all disappear.
Same move Carrefour made; it also removes Disco from the Selenium surface.

**D-2 — Discover subcategories from `/category/tree/2` at run time.**
The hardcoded 14-slug tuple is already 4 slugs wrong. Children are matched by
URL path under the requested category and the slug is the last path segment —
exactly Carrefour's `_discover_subcategories`.

**D-3 — Full coverage: partition by price when a node exceeds the 2550 window.**
Owner decision (2026-11-05): completeness over code minimalism.
`golosinas-y-chocolates` (6 210) and `desayuno-y-merienda` (13 317) cannot be
reached by paging alone, and the level-3 fallback would still lose 32 plus the
2 974 → 2 550 cut inside `galletitas-dulces` (≈1,2 % of almacén).
Instead: when a node's total exceeds `MAX_WINDOW`, take its measured price
range and bisect it with `fq=P:[lo TO hi]` until every bucket fits, then page
each bucket. Inclusive bounds make products on a boundary appear twice; the
`productId` dedupe set collapses them, so over-coverage is harmless and
under-coverage (`P` filter not indexing a product) is caught by the explicit
gap report below.

**D-4 — Identity is `productId`, not a name substring.** The API's
`productId` is stable and already what Carrefour stores as `sku`. The legacy
substring guard (`if not any(element['name'] in jsonitea['name'] ...)`) dropped
distinct products; it goes away with the HTML path.

**D-5 — Store `categoria="almacen"`, `subcategoria=<child slug>`.**
Carrefour's shape. The legacy Disco stored the child slug as `categoria` and no
`subcategoria`; aligning the shape is the point of the rewrite. There are **no
Disco documents in `lalistitadev.productos` today** (9 198 docs: Carrefour
6 187 + La Anónima 3 011), so nothing needs migrating. A database that still
holds legacy Disco docs keeps them until its own slice is replaced — noted in
`known-issues.md`.

**D-6 — Discovery failure is fatal; it never looks like "no products".**
Carrefour's R3-001 lesson: reporting a tree outage as zero subcategories would
end the run as a success and leave a stale slice. Network/status/JSON errors
while reading the tree are reported and re-raised, so the run manager marks the
run `failed`.

**D-7 — An incomplete collection is reported, never silently trimmed.**
Every child's final count is compared with the total the API reported. When a
node cannot be fully covered (price bisection that cannot split further, or a
`P` filter that indexes fewer products than the node total) the difference is
reported with a message naming the number, which is what the repo's
"no silent data loss" rule requires (see Carrefour's 1388 products).

**D-8 — `categories` stays `("almacen",)`.** Same accepted category as today;
the tree makes adding another one a one-line change later. No scope creep.

**D-9 — No retries.** A page failure inside a child propagates, the manager
marks the run `failed`, and children already saved keep their fresh data (the
same trade-off Carrefour documents). Bounded retry/backoff is a separate
decision, not invented here.

## 4. Contract the implementation must satisfy

Constants: `BASE_URL = "https://www.disco.com.ar"`,
`TREE_URL = f"{BASE_URL}/api/catalog_system/pub/category/tree/2"`,
`SEARCH_URL = f"{BASE_URL}/api/catalog_system/pub/products/search"`,
`PAGE_SIZE = 50`, `MAX_WINDOW = 2550`, `PAGE_SLEEP_SECONDS = 1`.

```
run(ctx):
  pre-cancelled guard (return)
  categories = (validated category,) or self.categories
  for categoria in categories:
      children = _discover_subcategories(ctx, categoria)   # D-6: raises on outage
      for (slug, label, path) in children:
          documents = _collect(ctx, path)                  # D-3, D-7
          if documents: ctx.save(documents, categoria=categoria, subcategoria=slug)
  report "PROCESO DETENIDO" when stopped, else "PROCESO TERMINADO"

_collect(ctx, path):
  total = _count(ctx, path, fq=None)          # resources header of _from=0&_to=0
  if not total: return []
  if total <= MAX_WINDOW: page the whole path (D-4 dedupe)
  else: lo, hi = _price_bounds(ctx, path) (O=OrderByPriceASC/DESC)
        bisect with _partition(...) until each bucket fits, paging buckets
```

Documents: `supermercado` = `self.label` ("Disco"), `name`/`unidad` from
`name_parse(productName)`, `brand`, `sku` = `str(productId)`, `price` from
`items[0].sellers[0].commertialOffer.Price` (0 when absent) — the same shape
`carrefour.py::_to_document` produces.

## 5. Tasks

- [x] **T1 — rewrite `api/scrapers/disco.py` and `tests/test_scraper_disco.py`.**
  Test-first: the new fake-HTTP test module is written first and observed red,
  then the scraper turns it green. Cases: tree discovery + child order,
  per-child save with `categoria`/`subcategoria`, window paging, the 2550
  ceiling, price-bucket bisection on an oversized node, boundary duplicates
  collapsed by `productId`, zero-total skip, fatal tree outage, page error
  propagation, stop during paging, pre-cancelled run, invalid category.
- [x] **T2 — docs sync.** `AGENTS.md` §6 (drop the page-1 quirk, state the API
  and the 2550 ceiling), `docs/agent-context/repo-map.md` (scraper row, quirks,
  browser list), `docs/agent-context/runbook.md` (quirk list),
  `docs/agent-context/known-issues.md` (substring-dedupe note and the
  "rendering needs `ctx.browser()`" list), `README.md` (the
  `Disco | Selenium` row).
- [ ] **T3 — live verification.** Real run of `aceites-y-vinagres` (1 478
  products measured) against the local MongoDB, `pytest`, the flake8 CI gate.

## 6. Verification evidence

**T1 (2026-11-05, `feat/disco-vtex-rewrite`, uncommitted worktree)**

- `pytest -q` → **334 passed, 9 skipped** (baseline before the rewrite: 321 passed, 9 skipped).
- `pytest tests/test_scraper_disco.py -q` → **22 passed** (the module had 9 tests before).
- `flake8 . --exclude .venv,adminpro,static,node_modules --select=E9,F63,F7,F82 --count` → **0**.
- RED observed before the implementation: `ImportError: cannot import name 'SEARCH_URL' from 'api.scrapers.disco'`.
- Independent verifier pass (fresh session, `git diff --name-only` = the two files only): no Selenium/browser/BeautifulSoup/`print()` left, every window is `_from=start&_to=start+49` with max `_to` 2549 for any cap in 0..2550, bisection is bounded and iterative, the three tree-outage paths report **and** re-raise, and the test module makes no network call.
- Ceiling regression guard: the fake session now answers 400 for `_to > 2549` / `_from >= 2501` like the live site, and `test_a_bumped_max_window_hits_the_live_ceiling_and_fails_the_run` proves a bumped `MAX_WINDOW` fails the run instead of silently collecting.
- Empty-bucket correctness measured live before pinning it: a zero-result filter answers **200** with `resources: 0-0/0` and body `[]` (not an error, not a missing header), so `test_an_empty_price_bucket_is_skipped_and_the_other_buckets_are_paged` pins that bisection survives a distribution gap.

**T2 (2026-11-05, `feat/disco-vtex-rewrite`, docs-only worktree)**

- Files touched (only docs): `AGENTS.md`, `README.md`,
  `docs/agent-context/repo-map.md`, `docs/agent-context/runbook.md`,
  `docs/agent-context/known-issues.md`, and this file. No `.py`, no tests, no
  code (`git diff --stat` confirms: six `.md` files only).
- `grep -rn -i disco AGENTS.md README.md docs/agent-context/*.md` was the
  claim inventory. Updated: `AGENTS.md` §6 (page-1 bullet replaced by the API
  path + 2550 ceiling bullet), `AGENTS.md` §4/§8 test counts, `repo-map.md`
  (disco scraper row, quirks paragraph, dedupe paragraph, `categoria`/
  `subcategoria` schema rows), `runbook.md` (browser note + quirk list),
  `known-issues.md` (K-18 `ctx.browser()` list, substring-dedupe observation
  now citing `changomas.py:178`, and a new minor observation with the VTEX
  search-API limits), `README.md` (`Disco | Selenium` row → `API VTEX`).
- Historical mentions left untouched on purpose: the K-18 original-analysis
  call-site list and the K-4 `/scraping-disco` route history describe the past.
- `pytest -q` → **334 passed, 9 skipped** (observed during T2, matches T1).

_Remaining evidence (T3) to be filled as it closes._

## 7. Out of scope

- Retry/backoff policy (D-9).
- A full 39 220-product almacén run: it is triggered from `/scrape` by the
  owner (~1,2 GB of JSON, 10-20 min) after the small live run passes.
- `name_parse` quirks (`known-issues.md`), unchanged here.
- The other four scrapers.
