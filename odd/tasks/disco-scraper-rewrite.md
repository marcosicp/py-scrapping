# Disco scraper rewrite — VTEX catalog API, complete coverage

**Branch:** `feat/disco-vtex-rewrite` (from `main`)
**Status:** DONE (T1, T1b, T2, T3) — live-verified; native review pending

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

**Live run of the T1 implementation (2026-11-05) — found the design flaw below.**

| Measurement | Result |
| --- | --- |
| `aceites-y-vinagres` collected live | 1 478 of 1 478 in 48 s, 0 duplicate `sku`, 350 with `price 0` |
| `golosinas-y-chocolates` collected live | **741 of 6 210** in 26 s; the run reported `5469 productos faltantes` |
| Products with a price, `almacen` | **4 703 of 39 220** — 34 517 (88 %) carry no price |
| `fq=P:[0 TO 0]` (the unpriced cluster) | `golosinas` 5 467 of 6 210; `desayuno-y-merienda` 11 621 of 13 317; `galletitas-dulces` 2 575 of 2 974 |
| `fq=P:[0 TO 100000000]` | the **full** total (6 210 on `golosinas`, 2 974 on `galletitas-dulces`) — the price filter itself does cover everything |
| `O=OrderByPriceASC` first price | 479.0 on `golosinas` (there are 5 467 products below it, priced 0) — **the sort does not return the true minimum** |
| `O=OrderByPriceDESC` inside `fq=P:[0.01 TO 1e8]` | 105 500 on `almacen` — the true priced maximum |
| Price-0 samples inspected | `IsAvailable: false`, `Price 0.0`, `priceRange: null` — out-of-stock entries |
| Carrefour already stored with `price 0` | 1 480 of 6 187 (same cause, pre-existing) |

## 3. Decisions

**D-1 — Read the catalog API, not the HTML. Drop the browser entirely.**
Both the tree and the search endpoint are plain GETs, so the Chrome driver,
the scroll, the class-name total and the BeautifulSoup parse all disappear.
Same move Carrefour made; it also removes Disco from the Selenium surface.

**D-2 — Discover subcategories from `/category/tree/2` at run time.**
The hardcoded 14-slug tuple is already 4 slugs wrong. Children are matched by
URL path under the requested category and the slug is the last path segment —
exactly Carrefour's `_discover_subcategories`.

**D-3 — Full coverage means full coverage of the available subset: page `fq=P:[0.01 TO max]`.**
Owner decision (2026-11-05), taken after the live measurement below.
A price comparer needs sellable products, and only **4 703 of `almacen`'s 39 220**
entries are available. `fq=P:` indexes **available offers only**, which is what
the storefront shows; the other 34 517 entries are `IsAvailable: false` and
split into two classes that are useless here — most carry a *stale* price
(measured on `aceites`: 928 of 1 478 have `Price` 8.69 / 864.29 against a
`ListPrice` of 718 / 71 429) and 350 carry `Price 0`. Those entries also form a
single atomic cluster no price filter can split (`P:[0 TO 0]` alone holds
5 467 on `golosinas`), so they cannot be paged in bulk at all — the tree
descent would recover most of them while still leaving ~456 unreachable in
`almacen` and storing 34 517 unusable rows.
The legacy scraper read the storefront HTML, which hides out-of-stock
products, so storing them would have been a regression, not a gain.
Collection scope is therefore the available subset, built with
`fq=P:[0.01 TO <measured priced max>]` and bisected by price when it exceeds
`MAX_WINDOW`. The exact count of omitted out-of-stock entries is reported per
child (`sin stock omitidos`) — the omission is a decision, never a silence.

Measured split of one child, `aceites-y-vinagres` (1 478 entries):

| Class | n | `Price` | `IsAvailable` | In `fq=P:` | Stored |
| --- | --- | --- | --- | --- | --- |
| Available | 200 | real | `true` | yes | yes |
| Out of stock, stale price | 928 | 8.69 / 864.29 (vs `ListPrice` 718 / 71 429) | `false` | no | no |
| Out of stock, no price | 350 | 0 | `false` | no | no |

**D-3a — The price range starts at the floor and its top is measured inside the filter.**
The first implementation bisected the range between the `OrderByPriceASC`
and `OrderByPriceDESC` prices of the **unfiltered** node. Measured live, `ASC`
returns 479 on `golosinas`, not the true minimum: 5 467 products price at 0 and
sit below it, so the run collected 741 of 6 210 and reported the rest as
missing. The low bound is now the constant `PRICE_FLOOR = 0.01` (a lower bound
is unsafe to infer from a sort) and the top is the `OrderByPriceDESC` price of
the **filtered** set, which is the real maximum.

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

**D-9 — Bounded retries for transient failures; everything else still fails fast.**
Measured live: the first full `almacen` run died at 93 s with
`RuntimeError: the search API answered 500`; the next run, same code and data,
finished all 15 children. With no retry a ~3-minute scrape is a coin flip, so
`_search` now makes **3 attempts** with a 2 s / 4 s backoff through `ctx.sleep`
(stop-aware), retrying **only** network errors and HTTP `>= 500`. A 4xx is a
wrong request, not a flaky server: reported and raised on the first attempt.
After the last attempt the failure is reported and re-raised, so the run
manager still marks the run `failed` and the children already saved keep their
fresh data. A stop requested during a backoff returns `None` instead of
raising, so a stopped run ends as `PROCESO DETENIDO`, never as `failed`.
The category tree keeps its single-shot behaviour: a tree outage is fatal
(D-6) and retrying it would only delay the inevitable.

## 4. Contract the implementation must satisfy

Constants: `BASE_URL = "https://www.disco.com.ar"`,
`TREE_URL = f"{BASE_URL}/api/catalog_system/pub/category/tree/2"`,
`SEARCH_URL = f"{BASE_URL}/api/catalog_system/pub/products/search"`,
`PAGE_SIZE = 50`, `MAX_WINDOW = 2550`, `PAGE_SLEEP_SECONDS = 1`,
`PRICE_FLOOR = 0.01` (excludes the unpriced cluster, D-3) and
`PRICE_CEILING = 100_000_000` (a synthetic upper bound, only used to scope the
filter until the real maximum is measured).

```
run(ctx):
  pre-cancelled guard (return)
  categories = (validated category,) or self.categories
  for categoria in categories:
      children = _discover_subcategories(ctx, categoria)   # D-6: raises on outage
      for (slug, label, path) in children:
          documents = _collect(ctx, path, label)           # D-3, D-3a, D-7
          if documents: ctx.save(documents, categoria=categoria, subcategoria=slug)
  report "PROCESO DETENIDO" when stopped, else "PROCESO TERMINADO"

_collect(ctx, path, label):
  total  = _fetch_total(ctx, path, label)                       # every entry
  priced = _fetch_total(ctx, path, label, (FLOOR, CEILING))     # D-3 scope
  if total > priced: report "<label>: <total - priced> sin precio omitidos"
  if not priced: return []
  if priced <= MAX_WINDOW: page (FLOOR, CEILING)                # D-4 dedupe
  else: hi = OrderByPriceDESC price within the priced filter     # D-3a
        bisect [FLOOR, hi] until each bucket fits, page each bucket
  gap = priced - collected; report it when > 0                   # D-7
```

Documents: `supermercado` = `self.label` ("Disco"), `name`/`unidad` from
`name_parse(productName)`, `brand`, `sku` = `str(productId)`, `price` from
`items[0].sellers[0].commertialOffer.Price` (0 when absent) — the same shape
`carrefour.py::_to_document` produces.

## 5. Tasks

- [x] **T1 — rewrite `api/scrapers/disco.py` and `tests/test_scraper_disco.py`**
  (commit `c21f226`; superseded by T1b below).
- [x] **T1b — correct the collection scope after the live measurement.**
  Collect only the priced subset (D-3) starting the range at `PRICE_FLOOR`
  with the top measured inside the filter (D-3a), report the omitted unpriced
  count per child, and make the test fake model the real API faithfully: an
  unpriced atomic cluster below the `OrderByPriceASC` value, price filters
  that exclude it, and the full unfiltered total. Cases to add: the atom is
  excluded and counted, a priced subset under the ceiling is paged whole, an
  oversized priced subset is bisected from the floor and covers 100 % of the
  priced total, and a fake-backed regression to the old ASC-bound range fails
  the suite.
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
- [x] **T3 — live verification.** Real run of the **whole `almacen`** (4 703
  priced products measured) against the local MongoDB on the final code, plus
  a re-run of `aceites-y-vinagres` to confirm the per-child slice shape,
  `pytest` and the flake8 CI gate.

## 6. Verification evidence

**T1 (2026-11-05, `feat/disco-vtex-rewrite`, uncommitted worktree)**

- `pytest -q` → **334 passed, 9 skipped** (baseline before the rewrite: 321 passed, 9 skipped).
- `pytest tests/test_scraper_disco.py -q` → **22 passed** (the module had 9 tests before).
- `flake8 . --exclude .venv,adminpro,static,node_modules --select=E9,F63,F7,F82 --count` → **0**.
- RED observed before the implementation: `ImportError: cannot import name 'SEARCH_URL' from 'api.scrapers.disco'`.
- Independent verifier pass (fresh session, `git diff --name-only` = the two files only): no Selenium/browser/BeautifulSoup/`print()` left, every window is `_from=start&_to=start+49` with max `_to` 2549 for any cap in 0..2550, bisection is bounded and iterative, the three tree-outage paths report **and** re-raise, and the test module makes no network call.
- Ceiling regression guard: the fake session now answers 400 for `_to > 2549` / `_from >= 2501` like the live site, and `test_a_bumped_max_window_hits_the_live_ceiling_and_fails_the_run` proves a bumped `MAX_WINDOW` fails the run instead of silently collecting.
- Empty-bucket correctness measured live before pinning it: a zero-result filter answers **200** with `resources: 0-0/0` and body `[]` (not an error, not a missing header), so `test_an_empty_price_bucket_is_skipped_and_the_other_buckets_are_paged` pins that bisection survives a distribution gap.

**T1b (2026-11-05) — the live run corrected the design twice**

- `pytest -q` → **340 passed, 9 skipped**; `flake8` CI gate → **0**.
- First live run of the T1 code (`golosinas-y-chocolates`, 6 210 catalog entries): collected **741**, reported `5469 productos faltantes`. Root cause: the bisection range started at the `OrderByPriceASC` price of the unfiltered node (479.0), and 5 467 entries priced 0 sit below it.
- Measurements that fixed it: `fq=P:[0 TO 100000000]` returns the full total, `fq=P:[0 TO 0]` isolates the atomic cluster (5 467 / 11 621 / 2 575), `OrderByPriceDESC` **inside** the filter gives the real maximum (105 500 on `almacen`), and the omitted entries are out of stock (`IsAvailable: false`).
- Second live run, whole `almacen` with the priced scope: **4 704 documents** across the 15 children in ~3 min (Mongo: `categoria=almacen`, one `subcategoria` per child, 1 document with `price 0`). No gap report fired for any child, and every child's `sin stock omitidos` matched the measured difference (e.g. `desayuno-y-merienda` 11 621 omitted / 1 696 stored).
- Third finding, from the same session: a full run died at 93 s on a transient **500**; the next identical run completed. That is why D-9 now has bounded retries (`ATTEMPTS = 3`, backoff 2 s / 4 s, 5xx and network only, 4xx still fatal on the first attempt).
- Test-first RED for T1b: **10 failed, 14 passed** before the priced-scope fix; **10 failed, 18 passed** before the retry policy; GREEN **28 passed** in the module afterwards.

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

**T3 (2026-11-05) — final live run of the whole `almacen`**

- A `python` harness driving the real `ScraperDisco.run(ctx)` against
  `www.disco.com.ar` and the local MongoDB (`lalistitadev`): **173 s**, 15/15
  children, `ctx.saved = 4704`, final report `PROCESO TERMINADO`.
- **Zero** `productos faltantes` reports: every child's available subset was
  collected completely. Every child reported its out-of-stock count
  (`aceites` 1 280, `desayuno-y-merienda` 11 622, `golosinas-y-chocolates`
  5 468, …), and each stored count equals the measured available total.
- MongoDB after the run: `supermercado=Disco` **4 704** documents, all with
  `categoria=almacen` and a `subcategoria`; price range 0–105 500 (the top
  matches the measured priced maximum); a single document with `price 0` (a
  product whose available offer is not `sellers[0]`).
  `lalistitadev.productos` total: 13 902.
- `/supermercados` → `disco: 4451` (name-deduped from 4 704), `carre: 5689`,
  `hiper: 2792`, `todos: 12 932` — the payload keys the Angular dashboard
  reads are unchanged.
- No 500 was hit on this run, so the retry path stayed dormant in production;
  it is pinned by tests (500→200, 500×2→200 with sleeps `[2, 4]`, 500×3 →
  propagate, 400 → no retry, network→200, stop during backoff).

## 7. Out of scope

- **Carrefour's 1 480 `price: 0` documents (24 %)** — same cause as D-3,
  owner decision 2026-11-05: documented here and in `known-issues.md` as its
  own follow-up, not touched in this feature.
- Retry/backoff policy (D-9).
- `name_parse` quirks (`known-issues.md`), unchanged here. The live run did
  surface one: `Aceite De Girasol1.5 L Natura` keeps the unit in the name
  because the shared helper's unit list has no bare `l` — pre-existing, shared
  by every scraper, and a separate work unit.
- The other four scrapers.
