# Feature: Carrefour scraper on the VTEX catalog API

STATUS: DONE (T1-T3) — commit `37a6286` on `feat/scrape-admin-view`
Owner request: "hagamos lo mismo con el scraper de Carrefour, su url es
https://www.carrefour.com.ar/ y con la categoría es
https://www.carrefour.com.ar/almacen".

## Why

Same treatment as La Anónima (`odd/tasks/scrape-admin-view.md`): replace a
scraper written against a moving facade with one that reads a machine-readable
source, discovers its own categories, and needs no browser.

The current `api/scrapers/carrefour.py` carries two collection paths, 18
hardcoded subcategory slugs, DOM class names for the product total
(`valtech-carrefourar-search-result-{0,3}-x-totalProducts--layout`), a
`window.scrollTo` loop, a **10-second sleep per subcategory**, and a Chrome
driver for the no-category path.

## Measurements (live, 2026-11-04)

| Probe | Result |
| --- | --- |
| `GET /almacen` | 200, **4.7 MB** of HTML, **0 JSON-LD blocks**, 8231 `vtex` markers |
| `GET /api/catalog_system/pub/products/search/almacen?_from=0&_to=2` | **206**, `resources: 0-2/**6188**` |
| Paging ceiling | `_from=2500` → 206, `_from=2501` → **400** |
| `GET /api/catalog_system/pub/products/search/desayuno-y-merienda?...` | 206, `resources: 0-0/**6768**` |
| `GET /api/catalog_system/pub/category/tree/2` | 200, 166 KB tree with `url` and `children` |
| Almacén children (10) | 437+694+453+533+1050+1224+207+546+892+152 = **6188**, an exact partition |
| Desayuno y merienda children (10) | sum **6769** vs parent 6768: one product sits in two subcategories |
| Largest subcategory | 1933 products → far below the 2500 ceiling |
| Product payload | `productName`, `productId`, `brand`, `items[0].itemId`, `items[0].sellers[0].commertialOffer.Price`, `categories` (full path) |

## Decisions

**D1 — Source is the VTEX catalog API, not the HTML.** `/almacen` is a 4.7 MB
VTEX shell with no JSON-LD; the API answers the same catalog as JSON with a
`resources: from-to/total` header that gives the exact page count.

**D2 — Granularity is the level-2 category, discovered from the tree.** The
2500-offset ceiling makes a flat crawl of `/almacen` (6188) impossible: the last
1388 products are unreachable that way. Every subcategory is under the ceiling,
and Almacén's children partition the parent exactly. The tree is read at run
time (`/api/catalog_system/pub/category/tree/2`) and matched by URL path, so a
new subcategory is picked up without a code change — the 18 hardcoded slugs go
away.

**D3 — No browser, one path.** Both webs scrape through `ctx.http`; the Chrome
path, the scroll loop and the DOM total classes are deleted. `desayuno-y-
merienda` keeps working, and a run without `category` iterates every registered
category instead of opening a driver.

**D4 — Stored identity.** `sku` comes from `productId` (the id in the product
URL, e.g. `...-122140/p`); the legacy stored an always-empty string because
VTEX search results have no `sku` key. Dedupe inside a subcategory is by that
id. `price` is `items[0].sellers[0].commertialOffer.Price` (float ARS), `0` when
the offer is missing, and `brand` is the payload's `brand`.

**D5 — Rate limit stays honest but small.** One `ctx.sleep(1)` per page request
(the legacy slept 10 s per subcategory and still hammered the driver). A full
`almacen` run is ~125 requests.

## Tasks

- [x] **T1 — Rewrite the scraper (test-first)** (`37a6286`). `api/scrapers/carrefour.py`
  rebuilt on the catalog API: tree discovery by category path, paged
  subcategory reads bounded by `resources`, `productId` identity, one
  `ctx.save` per subcategory, `PROCESO DETENIDO` on a stopped run. 18 canned
  tests, no network. The 273-line two-path module (driver, scroll loop, DOM
  total classes, 18 hardcoded slugs, 10 s sleeps) is gone.
- [x] **T2 — Reconcile what pinned the old shape.** `tests/test_scraper_carrefour.py`
  rewritten; `AGENTS.md` §6 quirk replaced by the VTEX paging ceiling;
  `repo-map.md` scraper table, categories note, quirks list and record schema;
  `runbook.md` browser list; `known-issues.md` dedupe note plus a new
  `name_parse` finding; `README.md` chain table.
- [x] **T3 — Verified live.** CLI run of `almacen` against the real site, Mongo
  and `/supermercados` checked below.

## Verification observed

| Check | Result |
| --- | --- |
| `pytest` | **309 passed / 9 skipped** (was 301: −10 old carrefour tests, +18 new) |
| flake8 CI gate + `F401,F811,F821,F841` | 0 / 0 |
| Live `python -m api.cli run carrefour --category almacen` | exit 0, **10 subcategorías, 6187 documents**, `state: succeeded`, ~128 paged requests with a 1 s pause |
| Mongo | 9198 documents total (`Carrefour` 6187 + `La Anónima` 3011), 10 Carrefour subcategorías |
| `GET /supermercados` | `carre = 5689` after name dedupe, `hiper = 2792`, `todos = 8481`, payload keys unchanged |
| Stored document sample | `supermercado=Carrefour`, `brand=Carrefour`, `sku=680457` (`productId`), `price=5348.6`, `categoria=almacen`, `subcategoria=aceites-y-vinagres` |
| No browser | every URL requested in the live run lives under `/api/catalog_system/` |

## Findings worth keeping

- **6187 vs 6188**: the catalog total for `aceites-y-vinagres` moved from 437 to
  436 between the measurement and the run (a product left the catalog). The
  saved total matches the live per-subcategory sum exactly:
  436+694+453+533+1050+1224+207+546+892+152 = 6187. Nothing was dropped by the
  collector; a page of 437 re-fetched now returns 436.
- **`_from=2501` → 400** while `_from=2500` → 206. That single measurement is
  the difference between a working collector and one that silently loses the
  last 1400 products.
- **`name_parse` mangles decimals**: `... pet 1.5 lts` is stored as `... pet 1.`
  with `unidad: "5 lts"`, because the pattern matches `5 lts` inside the
  decimal. Recorded in `known-issues.md`; the shared helper is untouched.
- The tree's children **partition** almacén exactly, so saving per subcategory
  replaces every slice without leaving orphans.

## Correction after the native review (R3-001, R3-002)

The review opened a bounded correction with two **deterministic CRITICAL**
findings, both introduced by this change:

- **R3-001 — a discovery outage reported success.** `_fetch_tree` swallowed a
  network error, a non-200 status or invalid JSON and returned `None`; the run
  read that as "no subcategories" and still reported `PROCESO TERMINADO`, so a
  total outage left the previous slice in place behind a green run. The previous
  browser path propagated a driver failure, so this was a regression. **Fixed**:
  the tree is now fatal — the error is reported and re-raised, the manager
  records `failed`, and the CLI exits 1.
- **R3-002 — decimal quantities corrupted names.** The unified mapper calls
  `name_parse` on every product, including the requested-category path that used
  to store raw names, and the helper split `pet 1.5 lts` into `pet 1.` +
  `5 lts`. **Fixed in the shared helper**: the quantity pattern accepts
  `\d+(?:[.,]\d+)?` and the removal escapes the match, so every scraper benefits
  and `tests/test_helpers.py` pins the decimal cases.

Correction declared at 95 diff lines (budget maximum 200) and verified with
**321 passed / 9 skipped** and a clean flake8 gate.

## Review state (blocked, needs an owner decision)

- Lineage `review-b7fc109d455348b7`, candidate `b544b60` scoped with
  `baseRef=4f11e73`, 8 files / 1439 lines, medium, one lens.
- Reviewer admitted; the provider refuter corroborated two deterministic
  CRITICAL findings -> `correction_required` with a bounded correction.
- Correction committed as `5c0c8d6` (declared plan 95 diff lines, actual 147,
  maximum 200).
- **The correction cannot be closed**: the provider's next transition is
  `recover` with `disposition=scope_changed`, because the fix touched
  `api/helpers.py`, a shared file outside the frozen candidate scope. Both
  `review.recover` invocations (with and without `lineageId`) fail with
  `recovery base-ref does not match predecessor base`, even though the rendered
  invocation carries `--base-ref`. This is the same facade/binary defect the
  previous session hit (the installed `gentle-ai` is the unpinned 4.3.1 dev
  override, not the pinned 4.0.0), not a defect in this candidate.
- Consequence: that lineage stays in `correction_required` with the correction
  committed and verified but unacknowledged.

### Second attempt: fresh review of the corrected candidate

A new lineage was started for the corrected candidate with `baseRef=4f11e73`,
which puts `api/helpers.py` **inside** the frozen scope from the start (so the
`scope_changed` recover can never fire again).

- Lineage `review-c4a3efb1e4e9e26f`, 10 files / 1571 lines, medium, same lens.
- Reviewer admitted; it downgraded two of its own findings with
  `unverified_location` (R3-002, R3-003).
- The provider refuter then **terminated the lineage**: state `escalated`,
  transition `stop` with `native_stop_required`, cause `unknown_causality` on
  R3-002/R3-003, and R3-001 `corroborated` **with the proof string
  `probe unavailable on pi`** — a corroboration with no probe behind it, the
  same false-positive pattern recorded in the previous session.
- A `stop` ends the transition and offers no correction route, so there is
  nothing to act on and nothing to acknowledge. **This is not an approval.**

Net review state for this feature: two open/terminal lineages
(`review-b7fc109d455348b7` in `correction_required`,
`review-c4a3efb1e4e9e26f` escalated/terminal) and no burned approval. What *is*
verified independently of the review: 321 tests, a clean lint gate, and a live
run of almacen storing 6187 documents, plus the two R3 findings fixed in
`5c0c8d6`.

## Follow-ups

- `desayuno-y-merienda` was not run live (6768 products, ~140 more requests).
  The path is covered by tests and shares all the code with `almacen`; run it
  when the owner wants that category in the database.
- One product sits in two `desayuno-y-merienda` subcategories (measured 6769 vs
  6768), so it will be stored twice under different `subcategoria` values.
  `/supermercados` dedupes by name, so the dashboard is unaffected.
- Environment note: a review preflight on this repo defaults to `base-ref
  d310d6c` (the whole unpushed backlog); scope it with an explicit `baseRef`.

## Risks

- ~125 network requests in one run against a real site, once, with a 1 s pause.
- The API could start requiring auth or change the paging ceiling; the run
  reports a non-206 page instead of saving silently.
- `desayuno-y-merienda` products that belong to two subcategories are stored
  twice under different `subcategoria` values (measured: exactly one product).
  `/supermercados` dedupes by name, so the dashboard is unaffected.
