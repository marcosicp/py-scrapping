# Feature: ChangoMás on the VTEX catalog API + its chain in the dashboard

STATUS: IN PROGRESS (T1-T4)
Owner request: "es hora de que arreglemos y acomodemos el scraper de ChangoMas.
Este es su dominio https://www.masonline.com.ar y tiene categoria /almacen.
Siempre mantene la linea con los otros scrapers. Ademas debes agregar su lista
en la cabecera del dashboard como tienen los otros supermercados".

## Why

`api/scrapers/changomas.py` is not a ChangoMás almacén scraper. It is a
quirk-preserving port of a browser module that never read `/almacen`:

- It drives Chrome (`ctx.browser()`) and starts at a hardcoded curated cluster,
  `DISCOVERY_URL = https://www.masonline.com.ar/3454?map=productClusterIds`
  (`changomas.py:54`), then builds section URLs from
  `SECTION_URL_PREFIX` — a template whose literal query string names
  `desayuno-y-golosinas/mas-online---almacen` (`changomas.py:58-61`).
- The page loop is `for i in range(2, 3)` (`changomas.py:142`): one iteration,
  so "pagination" is dead code.
- Inside that loop it re-fetches the **discovery** page and parses json-LD from
  it (`changomas.py:152-166`), not from the section it just visited.
- `categories = ()` (`changomas.py:85`), so `--category` is accepted and
  silently ignored.
- An empty gallery read `return`s out of the whole run (`changomas.py:139-140`)
  with no save and no report.

And the chain is invisible downstream: `api/services/matching.py::_bucket()`
maps only four buckets and returns `None` for `ChangoMas`
(`matching.py:73-89`), which `group_products` drops with
`continue  # ChangoMás or unknown origin (D-3)` (`matching.py:287-288`). The
dashboard has no column, no list and no header block for it. That is the open
half of K-12.

## Measurements (live, 2026-11-10)

| Probe | Result |
| --- | --- |
| `GET https://www.masonline.com.ar/almacen` | 200, VTEX (`x-vtex-renderer: render@8`, `x-vtex-product: store`) |
| `GET /api/catalog_system/pub/products/search/almacen?_from=0&_to=49` | **206**, `resources: 0-49/**4099**` |
| Paging ceiling | `_from=2500` → 206, `_from=2501` → **400** |
| `GET /api/catalog_system/pub/category/tree/2` | 200, 19 top-level nodes with `url` and `children` |
| Almacén children (9) | 420+429+92+325+349+160+1544+303+477 = **4099**, an exact partition |
| Largest subcategory | **1544** (`golosinas-y-chocolates`) → below the 2500 ceiling |
| Top-level totals (neighbouring scope) | hogar 6412, perfumería 5063, deportes 5170, bebés 2896 — all over the ceiling, none of them in `categories` |

## Decisions

**D1 — The source is the VTEX catalog API; Selenium is removed entirely.**
The storefront is VTEX, exactly like Disco and Carrefour. `/almacen` is a VTEX
shell; the API answers the same catalog as JSON with a
`resources: from-to/total` header. No driver, no scroll, no sleeps of 5 s.

**D2 — Granularity is the level-2 category, discovered from the tree.**
`almacen` holds 4099 products and the API refuses `_from=2501`, so a flat crawl
would lose the last ~1599. The nine children partition the parent exactly
(4099 = 4099) and the largest is 1544, so walking children is complete and
needs no price bisection (the Disco trick stays in Disco). The tree is read at
run time and matched by URL path, so a new subcategory is picked up without a
code change.

**D3 — `categories = ("almacen",)`, matching Disco.** The owner named `/almacen`.
Neighbouring top-level nodes exceed the ceiling and would each need their own
design decision, so they are not declared. `--category almacen` now works
instead of being ignored.

**D4 — The scraper mirrors `carrefour.py` structurally.** Same module helpers
(`_path_of`, `_slug_of`), same `_fetch_tree` / `_discover_subcategories` /
`_category_node` / `_scrape_subcategory` / `_total_from` / `_to_document` /
`_price_of` / `_ean_of` shape. No shared VTEX module is extracted: the repo
keeps one self-contained module per chain, and three call sites do not justify
a refactor that would rewrite Disco and Carrefour too.

Per-run state stays an instance attribute (`self._tree = None` in `run`), the
Disco behaviour, not Carrefour's class attribute — a class cache survives
across runs in one process and `tests/test_scraper_disco.py:354` punishes it.

**D5 — The chain bucket is `chang`.** Payload keys are short codes
(`carre`, `disco`, `mami`, `hiper`), not slugs. `chang` follows the convention
and a `changomas`/`changomás` substring in the stored `supermercado` value maps
to it.

**D6 — New ranks go last so existing tie-breaks do not move.**
`_BUCKET_ORDER` appends `"chang": 4`; `catalog()` concatenates
`supermami + carrefour + hiperlibertad + disco + changomas`. The four existing
relative orders — pinned by
`tests/test_products_api.py::test_stable_tie_break_across_supermarkets` — stay
byte-identical; only a five-way tie can change, and it could not happen before.

**D7 — Five chains do not fit `col-3`.** Bootstrap's grid is 12 columns, so the
header strip and the list row switch to `col` (auto-distributed) instead of
`col-3`.

**D8 — The header block is text, owner decision.** There is no ChangoMás logo
in `adminpro/src/assets/images/` and the storefront logo is React-rendered from
theme config, so it is not in the HTML. The owner chose a name-only block over
introducing a binary asset or an invented wordmark. Known inconsistency, owned:
the other four blocks show logos.

## Tasks

- [x] T1 — Rewrite `api/scrapers/changomas.py` on the VTEX catalog API and
      rewrite `tests/test_scraper_changomas.py` against it.
- [x] T2 — Surface the `chang` bucket: `api/services/matching.py`,
      `api/services/products.py`, `api/blueprints/products.py`, and invert the
      tests that pin ChangoMás as ignored.
- [x] T3 — Dashboard: `offers.chang` column, `itemsChang`/`totalChang`, toggle
      branch, fifth list panel, fifth header block (text), `col` layout.
- [x] T4 — Verification (`pytest`, `verify:selection`, flake8) and the
      `AGENTS.md` corrections for the two statements this invalidates.

## Verification observed

**T1** — `python -m pytest -q` → `449 passed, 9 skipped` (was 434/9: the 11
Selenium-era ChangoMás tests became 26 offline VTEX tests).
`tests/test_scraper_changomas.py tests/test_scraper_contract.py -q` →
`51 passed`. flake8 gate (`--select=E9,F63,F7,F82`) → `0`.

`grep -nE "selenium|BeautifulSoup|bs4|^import json|ctx.browser|print\("` over the
new module → no matches: no browser, no HTML parsing, no stdout reporting.

Live re-probe of the one shape the writer could not verify — the child search
path and the product payload — answered 206 with
`productId 219486`, `productName "Harina Leudante Blancaflor 1 Kg"`,
`brand "Blancaflor"`, `ean "7790070562180"`, `Price 2349.0`. The child path
`/products/search/almacen/harinas` is real, and the document shape matches
Carrefour's `_to_document` field for field.

**T2** — `python -m pytest -q` → `451 passed, 9 skipped`. flake8 gate → `0`.
Independently re-read after the writer reported: `_PAYLOAD_KEYS` carries
`chang`, `_BUCKET_ORDER` keeps `carre`0 / `disco`1 / `mami`2 / `hiper`3 and
appends `chang`4, `_bucket()` matches both spellings, `catalog()` concatenates
`supermami + carrefour + hiperlibertad + disco + changomas`, and all four
`api/blueprints/products.py` fallbacks carry `'chang': 0` (`grep -c` → 4).
The pin that asserted the opposite (`test_changomas_ignored_out_of_scope`) is
replaced by `test_changomas_documents_get_their_own_chang_bucket`, and the
spellings `ChangoMas` / `ChangoMás` / `CHANGOMAS` are covered in both layers.

**T3** — `npm run verify:selection` → `selection logic OK (19 checks)`.
`npx tsc -p tsconfig.app.json --noEmit` → exit 0, no output.
`grep -c "col-3"` over the template → `0`.

Diff read line by line: `selection.ts` untouched (it is chain-agnostic);
everything appended at the end, so the four existing columns, lists and toggle
branches keep their order. The ChangoMás header block is a 70px flex-centred
text block with a `badge-success` count — no image, no new asset, per D8.

Not verified here: the rendered page. Per AGENTS.md §8 an agent session never
opens a browser in this repo, so the visual check is the owner's.

**T4** — Final state of every gate:

| Gate | Command | Result |
| --- | --- | --- |
| Backend suite | `pytest -q` | `451 passed, 9 skipped` |
| CI lint gate | `flake8 . --exclude .venv,adminpro,static,node_modules --select=E9,F63,F7,F82 --count` | `0` |
| Angular logic | `cd adminpro && npm run verify:selection` | `selection logic OK (19 checks)` |
| Angular types | `cd adminpro && npx tsc -p tsconfig.app.json --noEmit` | exit 0 |

Documentation the feature invalidated, all corrected:

- `AGENTS.md` §4 test count, §6 ChangoMás quirk (was: "re-fetches the discovery
  page in its page loop"), §8 test count.
- `docs/agent-context/known-issues.md` — the K-12 index row and the K-12
  section are now `fixed`; the "substring dedupe in the remaining mechanical
  port" bullet no longer names a guard that does not exist.
- `docs/agent-context/repo-map.md` — the `changomas.py` row of the scraper
  table, the `/supermercados` payload example (`chang`), the grouping
  paragraph, the "quirks kept verbatim" bullet and the duplicate-suppression
  bullet.
- `docs/agent-context/runbook.md` — three stale `405 passed` statements.
- `README.md` — the ChangoMás row said "Selenium".

A `grep` for `selenium|json-ld|discovery page|half open|no branch|substring-based`
next to any ChangoMás mention over `AGENTS.md`, `README.md` and
`docs/agent-context/` now returns nothing.

## Correction after the native review (R3-001)

The native review (`review-reliability`, tier medium) raised one CRITICAL,
deterministic, candidate-introduced finding:

**R3-001** — a mid-subcategory network error, non-2xx response or invalid JSON
broke out of `_scrape_subcategory` and returned the documents collected so far;
`run` then saved that partial list and ended with `PROCESO TERMINADO`. Because
`replace_products` REPLACES the slice, a transient page failure could replace a
stored subcategory with a truncated catalog while the run looked successful.

This was inherited from `carrefour.py`, whose page errors `break` the same way.
`disco.py` already solved it for its search windows: 4xx raises on the first
attempt, 5xx/network retries then re-raises, and an incomplete collection is
always reported, never trimmed silently.

**Fix** — the three page failures now report that the partial collection will
not be saved and then raise (`api/scrapers/changomas.py`), so `run` never
reaches `ctx.save` for that subcategory: the previous slice stays intact and
the manager marks the run failed. `if not items: break` is unchanged, since an
empty page is how the API signals the end of a catalog.

**One test was passing because of the bug.**
`test_no_page_window_ever_reaches_or_crosses_the_2500_ceiling` queued only
three canned responses for two children, so the fake session raised
`AssertionError("unexpected extra GET")` on the second child — and the scraper's
own `except Exception: break` swallowed it, ending that child with zero
documents and letting the test assert its window list. The fix surfaced it as a
failure. The test now queues the responses it actually needs, so it pins the
ceiling on its own merits instead of relying on a swallowed error.

Correction size: **94 diff lines**, against the declared plan of 120 and the
frozen budget of 200.

## Follow-ups

- `tests/test_scraper_*.py` duplicate their VTEX doubles per module; a shared
  fake in `tests/fakes.py` is the obvious cleanup, deliberately out of scope.
- The header block for La Anónima still renders `libertad-logo.png`, the logo of
  the chain it replaced. Pre-existing, visible, unrelated to this feature.
- `carrefour.py` carries the same page-failure `break` that R3-001 flagged in
  ChangoMás, so the same truncation risk exists there and is now inconsistent
  with both `disco.py` and `changomas.py`. Pre-existing, unrelated to this
  feature, and worth its own task.
- `FakeSession` in the scraper tests signals "unexpected extra GET" with an
  `AssertionError`, which any `except Exception` in the code under test will
  swallow. R3-001 masked one test that way. A dedicated exception type would
  make that failure mode impossible to hide.
