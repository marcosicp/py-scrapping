# SuperMami scraper rewrite — Oracle Endeca, full category coverage

**Branch:** `feat/supermami-scraper-rewrite` (from `main`)
**Status:** DONE (T1-T3) — live-verified; native review pending

Rewrite `api/scrapers/supermami.py` with the same techniques that now work for
Carrefour, La Anónima and Disco: resolve the category from the site itself at
run time, take the structured product payload the page already embeds, dedupe
by product identity, and cover the category completely instead of a hardcoded
slice.

Requested by the owner: *"hacer el mismo trabajo en el super llamado SuperMami,
este es su sitio https://www.supermami.com.ar/ y empecemos por esta categoría
supermami-almacen."*

---

## 1. What the current scraper does (and why it must change)

`api/scrapers/supermami.py` is the mechanical port of the legacy module (T7):

- one **hardcoded URL** with the Endeca id `N-1tjm8rd` and a fixed `Nf`/`Nr`
  filter string copied from 2022;
- `MAX_PAGES = 2` — a literal from the legacy `range(1, 3)` — so it collects
  **72 of the category's 3 210 products** (2.2 %);
- reads the total from `p.txt-result` and computes `totalPages`, then ignores it;
- an empty page hit `continue`, which skipped the `countPages` increment, so the
  next iteration re-requested the same `No=` offset (a latent infinite loop);
- stores **no `sku`**, so nothing can be deduped by identity;
- `print()`s alongside `ctx.report`.

## 2. Measurements (2026-11-05, against `www.supermami.com.ar`)

Observed with `api/scrapers/http.py`'s shared session, i.e. the exact request
fingerprint the scrapers already use.

| Measurement | Result |
| --- | --- |
| `GET /supermami-almacen` | **404**; the root redirects to `/super/home` |
| VTEX catalog API (`/api/catalog_system/...`) | **403** (HTML error page) — SuperMami is **not** VTEX |
| Real platform | **Oracle Endeca**: `/super/categoria/<slug>/_/N-<id>`, paging with `No=` (offset) and `Nrpp=` (page size) |
| Legacy URL (`No=36&Nrpp=36`) | 200, 379 KB, `Resultado 37 a 72 de 3210` |
| `Nrpp=1000` | 200, 3.4 MB, **1 000 items** in one response |
| Offset ceiling | **none measured**: `No=2500&Nrpp=500` → 500 items, `No=3000&Nrpp=500` → 210, `No=3200&Nrpp=500` → 10 |
| Full category | 1 000 + 1 000 + 1 000 + 210 = **3 210**, exactly the reported total |
| Product payload | a `gtag('event', 'view_item_list', {...})` script with `item_id`, `item_name`, `item_brand`, `item_category`, `price` |
| Payload quality (4 pages) | every item has `item_id`, ids unique within each page, **no price 0**, 80 distinct `item_category` labels on page 1 |
| JSON API / JSON-LD / `__NEXT_DATA__` | none — the gtag script is the only structured source |
| Level-2 children of `almacen` | **15**, summing **2 680** vs the parent's **3 210** |
| Category menu | 539 category links; level 1 is `supermami-<category>` → `N-<id>`; level-2 items are `<li class="dropdown-submenu">` inside the parent's `<ul class="dropdown-menu">`, with their own nested `<ul>` for level 3 |

## 3. Decisions

**D-1 — The category is resolved from the site menu at run time.**
The hardcoded `N-1tjm8rd` and the 2022 `Nf`/`Nr` filter string go away. The run
reads the home/menu page once, finds the `supermami-<category>` link, and takes
its Endeca path and id. Adding `bebidas` later is a one-line change to
`categories`, exactly like Carrefour and Disco.

**D-2 — Page the parent category, not its children.**
Measured: the 15 level-2 children of `almacen` sum to 2 680 while the parent
reports 3 210 — **530 products (16 %) belong to no level-2 child**, so the
Carrefour/Disco "children partition the parent" assumption is false here.
Scraping the children would silently lose those 530. The parent is a superset
and, with no offset ceiling, fully reachable.

**D-3 — Big pages: `Nrpp=500`, offsets stepped by the page size, bounded by the
reported total.** 3 210 products take 7 requests instead of 90 at the legacy 36
per page. Paging stops when the reported total is reached, when a page comes
back empty, or on a cooperative stop — and the collected count is compared with
the reported total at the end (D-6).

**D-4 — The data source is the embedded gtag `view_item_list` JSON, parsed by
brace matching.** It is the only structured source (no JSON API, no JSON-LD) and
it already carries identity, name, brand, category and price. The legacy
`soup.find(text=...)` + `[:-2]` slicing is fragile; the rewrite extracts the JSON
object that follows the `view_item_list` marker and parses it, and treats a
missing or unparsable payload as a page error (D-7).

**D-5 — Identity is `item_id` (`prod…`), stored as `sku`.** The legacy stored no
identity at all. Dedupe is by that id across every page, which also absorbs the
one real risk of offset paging: Endeca re-ordering between requests.

**D-6 — One slice per category, with the product's own category as
`subcategoria`.** `ctx.save(documents, categoria=categoria)` keeps the prune
scope at `(SuperMami, almacen)`, while each document carries the site's own leaf
label (`item_category`, e.g. `Azúcar`) in `subcategoria`. That gives the
dashboard per-product granularity without fragmenting the slice, and the
end-of-run count is reported against the category total — an incomplete scrape
is never silent. There are **no SuperMami documents in `lalistitadev.productos`
today** (`mami: 0`), so the shape change needs no migration; a database that
still holds legacy documents (no `categoria` field) keeps them until its own
slice is replaced.

**D-7 — Transient failures get the bounded retry the Disco run established.**
3 attempts, 2 s / 4 s stop-aware backoff, only network errors and HTTP `>= 500`;
a 4xx fails on the first attempt. A missing/unparsable payload is treated like a
page error: reported, then raised after the attempts are exhausted. A stop
requested during a backoff ends the run as stopped, not failed.

**D-8 — `categories` becomes `("almacen",)`.** The legacy module accepted no
category (`categories = ()`), so the API/CLI category parameter was silently
ignored. Declaring it makes the accepted value explicit (an unknown one answers
400 like the other scrapers) and matches the site's own slug family.

**D-9 — The legacy quirks die with the rewrite.** The 2-page cap, the
same-offset repeat on an empty page, the missing `sku` and the `print()` calls
are removed. `name_parse` is unchanged (its quirks are documented in
`known-issues.md` and are shared by every scraper).

## 4. Contract the implementation must satisfy

Constants: `BASE_URL = "https://www.supermami.com.ar"`,
`MENU_URL = f"{BASE_URL}/super/home"`, `PAGE_SIZE = 500`,
`PAGE_SLEEP_SECONDS = 1`, `ATTEMPTS = 3`, `BACKOFF_SECONDS = (2, 4)`,
`TIMEOUT = 90`.

```
run(ctx):
  pre-cancelled guard (return)
  categories = (validated category,) or self.categories
  for categoria in categories:
      path = _discover_category(ctx, categoria)     # D-1, fatal on outage (D-7)
      total = _fetch_total(ctx, path)               # "de <strong>N</strong>"
      documents, seen = [], set()
      start = 0
      while start < total and not ctx.should_stop():
          page = _fetch_page(ctx, path, start)      # gtag JSON, D-4
          for item in page: add if item_id not in seen (D-5)
          start += PAGE_SIZE; ctx.sleep(PAGE_SLEEP_SECONDS)
      if len(documents) < total: report the exact missing count (D-6)
      if documents: ctx.save(documents, categoria=categoria)
  report "PROCESO DETENIDO" when stopped, else "PROCESO TERMINADO"
```

Documents: `supermercado` = `self.label` ("SuperMami"), `name`/`unidad` from
`name_parse(item_name)`, `brand` = `item_brand`, `sku` = `item_id`,
`price` = `price` (0 when absent), `subcategoria` = `item_category`.

## 5. Tasks

- [x] **T1 — rewrite `api/scrapers/supermami.py` and `tests/test_scraper_supermami.py`.**
  Test-first: the new fake-HTTP test module first (observed red), then the
  scraper. Cases: menu discovery (path + Endeca id resolved, unknown category
  reported), happy path paging across several pages with one save, the reported
  total as the paging bound, `item_id` dedupe across pages, missing/unparsable
  gtag payload, menu outage (network/status/invalid HTML) reported and raised,
  page error retry policy (500→200, 500×3, 400 no retry, network→200, stop during
  backoff), stop during paging saves what was collected, pre-cancelled run inert,
  invalid category raises `InvalidCategory`, missing price stored as 0.
- [x] **T2 — docs sync.** `AGENTS.md` §6 (drop the SuperMami 2-page quirk, state
  the Endeca path/paging), §4 and §8 test counts; `docs/agent-context/repo-map.md`
  (scraper row, quirks, record schema `subcategoria` row);
  `docs/agent-context/runbook.md` (quirk list); `docs/agent-context/known-issues.md`
  (the `MAX_PAGES = 2` note and the new Endeca measurements); `README.md`
  (`SuperMami | Selenium` row is already false — it is plain HTTP today).
- [x] **T3 — live verification.** Real run of `almacen` against the local
  MongoDB: expect **3 210 documents**, no missing-count report; then `pytest`
  and the flake8 CI gate.

## 6. Verification evidence

**T1 (2026-11-05, `feat/supermami-scraper-rewrite`)**

- `pytest -q` → **363 passed, 9 skipped** (baseline before the rewrite: 340 passed).
  `tests/test_scraper_supermami.py` → **28 passed** (the module had 12).
- `flake8 . --exclude .venv,adminpro,static,node_modules --select=E9,F63,F7,F82 --count` → **0**.
- RED observed twice: first `ImportError: cannot import name 'BASE_URL'`, then — after the
  fake menu was made faithful to the live page — **17 failures** whose diff showed the
  run paging `/super/categoria/supermami-almacen-aceites-vinagres-y-acetos-aceites/_/N-5j2xvv`
  instead of `/super/categoria/supermami-almacen/_/N-1tjm8rd`.
- **Discovery defect caught before the live run** (measurement, not review): the live
  `/super/home` has **263** anchors whose `href` contains `supermami-almacen`, and every one
  is a child or grandchild; the parent has **no `href` at all**, only
  `onclick="javascript:getPageCategory('/super/categoria/supermami-almacen/_/N-1tjm8rd', '', event);"`.
  A substring match therefore resolved `almacen` to a 75-product leaf and reported success.
  Fixed: candidates come from `href` **and** `onclick`, and the category segment must equal
  `supermami-<category>` exactly (`CATEGORY_PATH_RE`).
- One test outside the writer's surfaces pinned the old behaviour
  (`tests/test_container.py:189` asserted `categories == []` for supermami); updated to
  `["almacen"]` per D-8 as part of this task.
- Live run of `almacen` against the real site and the local MongoDB: **85 s, 7 pages,
  3 210 documents, `PROCESO TERMINADO`, no missing-count report** (evidence in T3 below).

**T2 (2026-11-05, `feat/supermami-scraper-rewrite`)**

- `grep -rn -i "supermami" AGENTS.md README.md docs/agent-context/*.md` turned
  up the live claims: `AGENTS.md:200` (the 2-page quirk bullet),
  `AGENTS.md:96` (the tests count, then 334), `AGENTS.md:263` (§8 default run,
  then 334), `repo-map.md:186` (scraper row), `repo-map.md:205` (quirks paragraph),
  `repo-map.md:224` (`sku` row, "absent for SuperMami"), `repo-map.md:228`
  (`subcategoria` row), `runbook.md:186` (categories list), `runbook.md:214`
  (quirk list), `README.md:13` (`SuperMami | Selenium` row). The remaining
  known-issues touches (`:83`, `:194`, `:238`, `:257`, `:273`, `:419`, `:459`,
  `:473`) are historical accounts of deleted legacy code, retained verbatim —
  not corrected.
- The `MAX_PAGES = 2` note the task expected in `known-issues.md` did not exist
  there (the grep showed it only in `repo-map.md:186`, `runbook.md:214` and
  `AGENTS.md:200`); all three are fixed, and the Endeca measurement was added
  as a new bullet under known-issues' "Minor observations (not filed)".
- Files touched: `AGENTS.md` (§4 tests count, §6 quirk bullet, §8 default run),
  `docs/agent-context/repo-map.md` (scraper row, quirks paragraph, `sku` and
  `subcategoria` schema rows), `docs/agent-context/runbook.md` (categories
  list, quirk list), `docs/agent-context/known-issues.md` (new Endeca
  observation), `README.md` (the SuperMami row only: `HTTP + Endeca (gtag JSON)`).
- Test count observed in this session: `.venv/bin/pytest -q` → **363 passed,
  9 skipped** (run twice, 2.14–2.21 s). No Python source was edited.

_Remaining evidence (T3) to be filled when the task closes._

## 7. Out of scope

- Other SuperMami categories (`bebidas`, `fresco`, …): the design makes them a
  one-line change, and the owner asked to start with `almacen`.
- The level-2 children as separate slices: D-2 explains why the parent wins.
- `name_parse` quirks (shared, documented, separate work unit).
- The other four scrapers.
