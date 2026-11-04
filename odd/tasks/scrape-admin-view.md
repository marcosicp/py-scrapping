# Feature: admin /scrape view + La Anónima scraper

STATUS: DONE (T1-T3)
Branch: `feat/scrape-admin-view` (from `main@a695e86`)
Owner request: "trabajemos en la vista de /scrape y empecemos por un solo scraper
como el de super mami, probemos con una sola categoria. Esta vista es solo para mi
como administrador del proyecto por eso esta fuera de Angular." — refined to
"empecemos por cambiar la url de hiperlibertad, ahora es
https://www.laanonima.com.ar/almacen y 'almacen' es la categoria".

## Why

`/scrape` is the only admin surface for running scrapers, and it is in bad shape:
a malformed document, three unused CDN frameworks (jQuery 2.1.1, Bootstrap 3.2,
the Tailwind Play CDN), a 404 on `static/assets/style.css`, buttons wired to the
deprecated `/scraping-<slug>` aliases, error handling that only understands 409,
no initial state on reload, an unbounded progress log, and no display of the run
outcome (`saved`, duration, `message`, `category`) that the API already returns.

While scoping the first end-to-end run we found the blocker underneath: the
scraper chosen for the smoke test is dead.

## Decisions (with evidence)

**D1 — HiperLibertad no longer exists; the scraper is La Anónima.** Verified:
`GET https://www.hiperlibertad.com.ar/` → **301** to `https://www.laanonima.com.ar/`;
the VTEX endpoint the scraper consumes
(`/api/catalog_system/pub/products/search/...`) answers **403**. La Anónima is not
VTEX: Apache/2.4 + Smarty + CloudFront, `robots.txt` listing `/ui_smarty/`.

**D2 — Rename to `laanonima`** (user decision). slug `laanonima`, label
`La Anónima`, `supermercado: "La Anónima"` in Mongo. `lalistitadev.productos` has
**0 documents**, so no data migration. Cost: `api/scrapers/hiperlibertad.py` →
`api/scrapers/laanonima.py`, `default_registry()`, tests that name the slug,
`AGENTS.md` §4 table, `docs/agent-context/repo-map.md`, `README.md`.

**D3 — Data source is the page's JSON-LD, not HTML scraping.** Every category page
embeds `<script type="application/ld+json">` with an `ItemList` of `Product`
entries: `name`, `url` (`.../art_<id>/`), `image`, `offers.price` (ARS, integer),
`offers.availability`. No CSS selectors to maintain, no market/brand parsing.

**D4 — Granularity is the n2 node.** The site's nav menu carries the category tree:
`a.menu-n1` → `a.menu-n2` → `a.menu-n3`. Under `Almacén` (`/almacen/n1_512/`)
there are **11 n2** and **30 n3** nodes. A n2 page already **includes its n3
children** — measured: `/aceite-aderezos-y-condimentos/n2_524/` = 373 items,
its child `/aderezos/n3_847/` = 125 items, a subset with the same first product —
so scraping both would duplicate. The n1 page itself reports only **201** items
(truncated, not the union), so it is not a valid source either. Therefore: one GET
per n2 node, `ctx.save(items, categoria="almacen", subcategoria=<n2 slug>)`.

**D5 — Discovery is dynamic, from the menu.** The node ids (`n2_521`…) are not
derivable and the tree belongs to the site, not to us: parse the menu on
`/almacen/n1_512/` and walk the n2 anchors inside the Almacén `<li>`. A redesign
that removes the menu must fail loudly (report + return zero nodes) instead of
saving nothing silently.

**D6 — Dedupe by `sku`, not by name substring.** The legacy guard
`any(element['name'] in new['name'])` is O(n²) and drops distinct variants after
`name_parse` strips the unit. The `art_<id>` in the product URL is a stable exact
identity.

**D7 — /scrape keeps its own CSS, inline, zero third-party requests** (user
decision). No jQuery (the only use is `$.append`), no Bootstrap (no modals), no
Tailwind Play CDN (a JIT compiler fetched at page load). The stylesheet lives in
the template's `<style>` block so it cannot 404 and needs no route, no build step
and no cache-busting.

**D8 — /scrape stays unauthenticated this iteration** (user decision). K-13 stays
open in `docs/agent-context/known-issues.md` as the pre-deploy gate.

## Tasks

- [x] **T1 — La Anónima scraper replaces HiperLibertad** (`d852a5d`). Renamed to
  `laanonima`; the n2 nodes are discovered from the menu; one GET per node;
  the JSON-LD `ItemList` is the source; saved per subcategory. Test-first with
  canned menu and ItemList HTML (15 new tests). Registry, `ProductService`
  bucketing, `AGENTS.md` and `docs/agent-context/` reconciled in the same
  commit; the legacy module and its 11 tests are gone.
- [x] **T2 — `/scrape` rewrite** (`3c714a2`). Valid HTML5 document, self-contained
  `<style>`, registry-driven cards, category `<select>`, buttons against
  `/api/scrapers/<slug>/start|stop`, initial state from `GET /api/scrapers` plus
  one poll per second, full error surface (400 with `allowed`, 404, 409),
  `active`-driven button states, bounded log and an outcome panel.
  Follow-up fix in the same task: a cancelled run reported `PROCESO TERMINADO`
  (`6a550c8`).
- [x] **T3 — Close.** Docs updated (`AGENTS.md`, `repo-map.md`, `runbook.md`,
  `known-issues.md` dispositions), full suite and lint gate green, and the
  verification below actually run.

## Verification observed

| Check | Result |
| --- | --- |
| `pytest` | 301 passed / 9 skipped (baseline was 291 / 9) |
| flake8 CI gate (`--select=E9,F63,F7,F82 --count`) | 0 |
| `flake8 --select=F401,F811,F821` on touched files | 0 |
| `python -m api.cli list` | `supermami, laanonima, disco, carrefour, changomas` with their categories |
| Live CLI run `python -m api.cli run laanonima` | exit 0, **11 subcategorías, 3011 documents**, `state: succeeded` |
| Mongo | `supermercado` only `La Anónima`; 11 `subcategoria` values |
| `GET /supermercados` | `hiper = 2792` (dedupe by name), payload keys unchanged |
| `GET /scraping-laanonima-stop` | 409 `not_running` (route exists) |
| `GET /scraping-hiperlibertad-stop` | 404 (alias gone, as decided) |
| Browser, initial load | 5 cards, state from the API (not the literal `—`), start enabled / stop disabled, `<select>` only on the 3 scrapers with categories |
| Browser, forced 409 | notice shown and still visible after two polls |
| Browser, start → stop on La Anónima | `running` (buttons flip, select disabled) → `saved 1112`, `duration 7 s`, message advancing, log appending → `stopping` → `stopped`, saved 1669 |
| `node --check` on the page script | syntax clean |

## Findings worth keeping

- `ProductService.catalog()` buckets by **substring of `supermercado`** with the
  keys Angular reads (`carre`, `disco`, `mami`, `hiper`). Renaming the chain
  without touching it would have persisted data the dashboard silently drops;
  La Anónima now lands in the `hiper` bucket along with any legacy
  `HiperLibertad` documents.
- The site's n1 page reports 201 products while one of its n2 children reports
  373: the n1 page is truncated, so it is not a valid source. Only the n2 level
  is complete.
- `name_parse` leaves a dangling ` x` when the unit is preceded by one; recorded
  in `known-issues.md` minor observations with the measured example.
- The header's `<link>` to `static/assets/style.css` could never work: that path
  belongs to the Angular bundle, which does not emit it. Inline `<style>` cannot
  regress the same way.

## Follow-ups (not done here)

- **Socket.IO has no consumer left.** `api/sockets.py`, the
  `scraping-message-<slug>` and `scraper-status` channels still exist and still
  emit, but `/scrape` no longer subscribes. Either remove them (and the
  container wiring) or declare a consumer — an explicit decision, not a silent
  cleanup.
- `README.md` is still stale in ways this feature did not cause (`Angular 16`,
  the deleted `scrap_*.py` tree, the Selenium-per-chain table). AGENTS rule 4
  says correct the README; it deserves its own reviewed work unit.
- `/scrape` stays unauthenticated (D8). K-13 remains the pre-deploy gate.

## Risks

- The site can change the menu markup or the node ids; D5 fails loudly by design.
- 11 nodes × up to ~400 products = a real scrape against a real site: kept to one
  run per work unit, with `CHROME_HEADLESS` irrelevant (no browser involved).
- Renaming the slug removes `/api/scrapers/hiperlibertad` and
  `/scraping-hiperlibertad`; nothing live points at them (`templates/index2.html`
  is dead, `README.md` is stale and gets fixed here).
