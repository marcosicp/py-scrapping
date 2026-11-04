# Feature: admin /scrape view + La Anónima scraper

STATUS: IN PROGRESS
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

- [ ] **T1 — La Anónima scraper replaces HiperLibertad.** Rename to
  `laanonima`; discover the n2 nodes from the menu; one GET per node; read the
  JSON-LD `ItemList`; save per subcategory. Test-first with canned menu and
  ItemList HTML (no network). Registry, docs and every test that names
  `hiperlibertad` reconciled in the same commit.
- [ ] **T2 — `/scrape` rewrite.** Valid HTML5 (`<!DOCTYPE>`, `charset`,
  viewport), self-contained CSS, one card per registry scraper built from
  registry data, `<select>` of the scraper's categories (free text only when the
  scraper accepts no category), buttons against `/api/scrapers/<slug>/start|stop`,
  full error surface (400 `invalid_category` with `allowed`, 404, 409), initial
  state fetched on load, button enable/disable from `active`, bounded progress
  log, and the outcome panel: `state`, `category`, `saved`, duration from
  `started_at`/`finished_at`, `message`.
- [ ] **T3 — Close.** Docs (`AGENTS.md`, `docs/agent-context/repo-map.md`,
  `README.md`, `known-issues.md` dispositions), full `pytest` + flake8 CI gate,
  and a real verification: CLI run of `laanonima` against the live site with a
  Mongo count per `subcategoria`, plus a browser pass over `/scrape` starting and
  stopping a run.

## Verification plan

- `pytest` (baseline 291 passed / 9 skipped) and the flake8 CI gate
  (`--select=E9,F63,F7,F82 --count`) at zero.
- La Anónima: canned-HTML unit tests for discovery, JSON-LD parsing, dedupe,
  missing price, empty node and stop; then a live CLI run and
  `db.productos.aggregate(group by subcategoria)`.
- `/scrape`: browser check — reload during an active run shows `running` and the
  disabled state; a 400 surfaces the allowed categories; the log stays bounded;
  the outcome panel shows `saved` and duration.

## Risks

- The site can change the menu markup or the node ids; D5 fails loudly by design.
- 11 nodes × up to ~400 products = a real scrape against a real site: kept to one
  run per work unit, with `CHROME_HEADLESS` irrelevant (no browser involved).
- Renaming the slug removes `/api/scrapers/hiperlibertad` and
  `/scraping-hiperlibertad`; nothing live points at them (`templates/index2.html`
  is dead, `README.md` is stale and gets fixed here).
