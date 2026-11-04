# Repository map

Deep reference for the LaListita codebase. Verified against
`feat/backend-architecture@30b20cb` (T1-T14a committed). Entry point for agents
is [`AGENTS.md`](../../AGENTS.md); this file is the detail behind it.

---

## 1. Layers

```
HTTP layer      api/blueprints/{frontend,products,scrapers,legacy}.py
                thin views; errors → JSON; read services from app.extensions
   │
Services        api/services/{products,scraping}.py
                ProductService.catalog() / ScraperManager (runs, stops, status)
   │
Ports           api/repositories/products.py (ProductRepository)
                api/scrapers/{base,registry,errors}.py (scraper contract)
   │
Infrastructure  api/repositories Mongo adapter · api/scrapers/{http,browser}.py
                api/sockets.py (SocketIO) · api/config.py (Settings)
```

The composition root is `api/container.py` (`init_services`), called once by
`create_app()`; `get_services()` reads `app.extensions['lalistita']`. No layer
below the blueprints imports Flask. Tests inject fakes through `create_app`
keyword arguments (repository, registry, reporter).

The run manager is **in-process**: one active run per slug, one daemon worker
thread each, cooperative stop via a per-run `threading.Event`
(`api/services/scraping.py`). With more than one gunicorn worker each process
would own a private run table — status and single-flight guarantees would be
per-worker only. The deployment therefore assumes a single worker
(the Dockerfile CMD runs `--workers 1`).

## 2. Request flow

```
                    ┌──────────────────────────────────────┐
  browser ─────────►│  Flask  app.py :3000                 │
                    │  CORS(app) — everything              │
                    └───────┬──────────────────────────────┘
                            │  blueprints frontend, products, scrapers, legacy
                    ┌───────▼──────────────────────────────┐
                    │  api/blueprints/*.py                 ├──► api/container.py (Services)
                    └──┬──────┬──────────────┬─────────────┘
                       │      │              │
         send_from_dir │      │ GET /super…  └──► ScraperManager ─► worker thread
         (static/)     │      │                    │  ctx.report                        │
                       │      │                    ▼                                   ▼
                       │      │        api/scrapers/*.py (BaseScraper) ──► api/sockets.py
                       │      │        ctx.http / ctx.browser()               SocketIO.emit
                       │      │        ctx.save ──► ProductRepository               │
                       │      │                    │                                ▼
                       │      ▼                    ▼                     templates/scrape.html
                       │  ProductService → api/repositories/products.py    (live monitor)
                       │                    │
                       ▼                    ▼
              static/index.html     Mongo: lalistitadev.productos
         (Angular 21 bundle —
          gitignored, built locally)
```

## 3. Bootstrap — application factory

`app.py` exposes `create_app()`. Two entry points share it:

| Entry point | Used by | Server |
| --- | --- | --- |
| `python app.py` | local development | Werkzeug, `debug=True` |
| `gunicorn main:app` | Docker and any WSGI host | `main.py` calls `create_app()` at import |

| Step | Where | What happens |
| --- | --- | --- |
| `load_dotenv()` | module scope | `.env` optional; defaults apply without it |
| `Flask(__name__, static_url_path='')` | `create_app` | `static/` is served at the URL root |
| `CORS(app)` | `create_app` (`app.py:74`) | every origin allowed, including scraper-control POSTs (K-13) |
| `SECRET_KEY` | `create_app` (`app.py:76`) | from `Settings.from_env`; default `'secret!'` (K-13) |
| `configure_sockets` | `create_app` | SocketIO initialized for **every** entry point (K-1) |
| `_init_mongo` | `create_app` | `MongoClient(connect=False)` + `app.database` (K-2, K-3) |
| `init_services` | `create_app` | `Services` in `app.extensions['lalistita']`; tests inject repository/registry/reporter |
| `register_blueprints` | `create_app` | `frontend`, `products`, `scrapers`, plus the registry-generated legacy aliases |

Three properties worth knowing:

- **Nothing is wired at import time in `app.py`.** `main.py` builds the
  module-level `app` WSGI servers expect. `gunicorn app:app` does not exist;
  use `main:app`.
- **`MongoClient` is lazy** (`connect=False`), so importing the app opens no
  socket and cannot hang a worker boot.
- **`async_mode` is `threading`** — no `eventlet`/`gevent` in the tree — so
  realtime works over long-polling, not over a WebSocket upgrade.

## 4. Endpoints

Four blueprints share the URL map (18 rules): `frontend`, `products`,
`scrapers` (`/api/scrapers`) and the registry-generated `legacy_scraping`
aliases, all thin HTTP shells over services.

### `api/blueprints/frontend.py`

| Method | Path | Handler | Real behavior |
| --- | --- | --- | --- |
| GET | `/` | `frontend.root` | `send_from_directory(static, index.html)`; **503 with the build command** when the bundle is absent |
| GET | `/scrape` | `frontend.scrape` | renders `templates/scrape.html` from the registry (one card per registered scraper) |
| GET | `/<path:filename>` | Flask static | serves the Angular bundle from `static/` |

### `api/blueprints/products.py`

| Method | Path | Handler | Real behavior |
| --- | --- | --- | --- |
| GET | `/supermercados` | `products.supermercados` | `ProductService.catalog()` through the `ProductRepository` (Mongo `lalistitadev.productos`); any exception → empty payload + `error` key, HTTP 200 |

### `api/blueprints/scrapers.py` — scraper control (`/api/scrapers`)

Body shape of every status entry: `{**status.to_dict(), "categories": [...]}`
(a `RunStatus` snapshot of `ScraperManager` plus the scraper's accepted
categories).

| Method | Path | Success | Error codes |
| --- | --- | --- | --- |
| GET | `/api/scrapers` | 200 `{"scrapers": [...]}` | — |
| GET | `/api/scrapers/<slug>` | 200 status + categories | `unknown_scraper` (404) |
| POST | `/api/scrapers/<slug>/start` | 202 status + categories | `unknown_scraper` (404), `invalid_category` (400, with `allowed`), `already_running` (409) |
| POST | `/api/scrapers/<slug>/stop` | 202 status + categories | `unknown_scraper` (404), `not_running` (409) |

Error bodies are `{"error": ..., "code": ...}`; the category may come from the
query string or a JSON body. Unrecognized `ScraperError` subclasses are
re-raised, so unexpected failures still surface
(`api/blueprints/scrapers.py::error_payload`).

### `api/blueprints/legacy.py` — registry-generated aliases

For each registered slug (`supermami`, `hiperlibertad`, `disco`, `carrefour`,
`changomas`):

| Method | Path | Behavior |
| --- | --- | --- |
| POST | `/scraping-<slug>` | alias of `/api/scrapers/<slug>/start` — 202, or the same error codes with `{"success": false, ...}` |
| GET/POST | `/scraping-<slug>-stop` | alias of `/api/scrapers/<slug>/stop` — `{"success": true}` on 200 |

DEPRECATED: they exist for the legacy `/scrape` page and scripts. Unlike the
deleted `api/routes.py` routes they never block the request and never run a
second copy of the same scraper (a second start is a clean 409).

There is no auth, no pagination, no filtering, and no write API other than
"start a scraper" (K-13).

### `/supermercados` contract

```json
{
  "todos":  [ { "supermercado": "Disco", "name": "...", "unidad": "500 ml",
                "brand": "...", "sku": "...", "price": "1234.00",
                "scraped_at": "2026-11-03T12:00:00Z", "categoria": "almacen" } ],
  "carre":  0,
  "disco":  0,
  "mami":   0,
  "hiper":  0
}
```

Grouping is substring matching on the lowercase `supermercado` field
(`api/services/products.py:36-43`, first match wins): `disco`, `carrefour`,
`hiper*`, `mami*`. **ChangoMás has no branch** (K-12, API half open), so its
products never appear. Dedupe is `remove_duplicates_by_key(list, 'name')` —
first occurrence wins (`api/helpers.py:3-8`). On any exception the blueprint
returns an empty payload plus an `error` key rather than failing loudly
(`api/blueprints/products.py`).

## 5. Scrapers — `api/scrapers/`

All five supermarkets implement the same contract: a `BaseScraper` subclass
(`slug`/`label`/`categories`/`run(ctx)`) registered in `default_registry()`
(`api/scrapers/registry.py`), driven by `ScrapeContext`
(`api/scrapers/base.py`): `ctx.report(text)` for progress, `ctx.http` for the
shared requests session, `ctx.browser()` for a Chrome driver (built once by
`api/scrapers/browser.py`, quit in a `finally`), `ctx.save(...)` to persist
through the repository, `ctx.should_stop()`/`ctx.sleep()` for cooperative stop.
A scraper never imports Flask, Mongo or SocketIO.

| Scraper | Technique | Persists to | Notes |
| --- | --- | --- | --- |
| `supermami.py` | plain HTTP + gtag `view_item_list` extraction | Mongo via `ctx.save` | no browser, no `sku`; capped at 2 pages (`MAX_PAGES = 2`, `:24`); no categories accepted |
| `hiperlibertad.py` | plain HTTP against the VTEX JSON API (`api/catalog_system/pub/products/search`), 14 hardcoded subcategories, 50-item `_from`/`_to` paging | Mongo per subcategory | no browser at all (the legacy driver was unused); accepts `almacen` |
| `disco.py` | Chrome driver nav + VTEX `?page=` paging + JSON-LD `itemListElement` | Mongo per subcategory | **page 1 is never collected** (`:108` loop starts at `?page=2`); accepts `almacen` |
| `carrefour.py` | two paths: requested category → plain HTTP + JSON-LD; all categories → Chrome driver + `render-provider` script | Mongo per category | Path A stores no `unidad` and skips `name_parse` (legacy omission kept); accepts `almacen`, `desayuno-y-merienda` |
| `changomas.py` | Chrome driver over the discovery page, section discovery, JSON-LD | Mongo via `ctx.save` | page loop re-fetches the **discovery** page (`:152`); empty first result aborts the whole run; label `ChangoMas`; **not shown by `/supermercados`** (K-12) |

Common details:

- **Driver:** the only construction site is `build_chrome(settings)`
  (`api/scrapers/browser.py`): `--no-sandbox`, `--disable-dev-shm-usage`,
  `--headless=new` when `CHROME_HEADLESS` is on, and `CHROMEDRIVER_PATH` for
  the binary — unset means Selenium Manager (needs network on first use).
- **Categories:** hardcoded tuples inside each scraper; `start` validates them
  and raises `invalid_category` with the allowed list
  (`BaseScraper.validate_category`, `api/scrapers/base.py`).
- **Quirks kept verbatim** by the mechanical ports: Disco skips page 1;
  ChangoMás re-fetches the discovery page; ChangoMás's empty-first-result abort
  ends the whole run; SuperMami caps at 2 pages; Carrefour Path A skips
  `name_parse`. Fixing any of them changes collected data and must be validated
  against a real run first (see `docs/agent-context/known-issues.md`).
- Duplicate suppression is substring-based and O(n²) per page:
  `if not any(element['name'] in jsonitea['name'] for element in jsondata)`.

### Record schema

| Field | Source | Notes |
| --- | --- | --- |
| `supermercado` | scraper `label` | `Disco` / `Carrefour` / `HiperLibertad` / `SuperMami` / `ChangoMas` |
| `name` | JSON-LD / gtag item, size suffix stripped by `name_parse` | Carrefour Path A skips `name_parse` |
| `unidad` | `name_parse` output, e.g. `"500 ml"` | comma-joined when multiple matches; absent in Carrefour Path A |
| `brand` | item brand | Hiper uses `.get("brand", "")` |
| `sku` | item sku | absent for SuperMami |
| `price` | `item.offers.lowPrice` | stored as a string |
| `scraped_at` | UTC stamp added by `MongoProductRepository.replace_products` (`api/repositories/products.py:77`) | `datetime.now(timezone.utc)` |
| `categoria` | the request/subcategory label | |
| `subcategoria` | HiperLibertad only | |

`name_parse` (`api/helpers.py:14`) regex:
`(\d+|X\d+)\s*(kg|kgs|g|gr|grs|ml|mls|m|cc|lt|lts)\b`, case-insensitive.

`api/models/productos.py` is **not** part of the schema — it is mongoengine-style
code against `pymongo` and is imported by nothing.

## 6. Mongo usage

| Concern | Value |
| --- | --- |
| Client injection | `app.mongodb_client`, created by `_init_mongo` in `create_app` (K-2) |
| Database | `MONGODB_DB`, default `lalistitadev` (`api/config.py`) |
| Collection | `productos` (`api/repositories/products.py::COLLECTION_NAME`) |
| Access pattern | raw `pymongo` through the `ProductRepository` port — `find_all` reads, `replace_products` writes (insert first, then prune; empty scrape is a no-op, K-8); no ODM, no indexes, no migrations |
| Env var | `MONGODB_URI`, default `mongodb://localhost:27017/` |

## 7. Frontend — `adminpro/`

- Angular **21.2.x**, **NgModule-based** (`app.module.ts`,
  `app-routing.module.ts`) — the standalone-migration flags are `standalone:
  false`, deliberate, from the PR #18 migration.
- Build system: `@angular-devkit/build-angular:application`;
  `outputPath: { base: "../static", browser: "" }` (`angular.json:16-19`) →
  output lands directly in `static/`, which is **gitignored**: a build produces no
  git diff, and a fresh clone must build before `/` answers.
- Global scripts loaded via `angular.json` from `node_modules`: jQuery, Popper,
  Bootstrap 4.6, plus `src/assets/js/*` (perfect-scrollbar, sidebarmenu, custom,
  jQuery.style.switcher) — AdminPro template heritage.
- Routes (`app-routing.module.ts`): `''` → `dashboard`; `dashboard` wrapper
  (`PagesComponent`) with children `''` → `DashboardComponent`, `progress`,
  `grafica1`; plus `login`, `register`, and `**` → `NoPageFoundComponent`.
  Auth guards exist only as comments.
- Grid: **ag-grid 32.3.9** in `pages/dashboard/dashboard.component.*`, with a
  custom cell renderer in `pages/dashboard/cellRender.ts`. Theming is
  `ag-theme-alpine`, loaded by CSS import in `adminpro/src/styles.css:3-4`
  (`ag-grid-community/styles/ag-grid.css`, `.../ag-theme-alpine.css`); the
  equivalent `unpkg.com` `<link>` tags in `adminpro/src/index.html:25-26` are
  commented out — leave them that way.
- HTTP: `service/app.service.ts` — a single `getExams()` method that GETs
  `http://127.0.0.1:3000/supermercados`. **No `environments/` directory exists**,
  so the API base URL is a literal and cannot vary per build.
- Real-time: the Angular app does **not** use SocketIO. Only
  `templates/scrape.html` does.

## 8. Templates and static

| Path | Reality |
| --- | --- |
| `templates/scrape.html` | The only rendered template (`api/blueprints/frontend.py`, `scrape`). Registry-generated: one card per registered scraper. Loads SocketIO 4.0.1 from cdnjs and subscribes to `scraping-message-<slug>` channels plus the aggregated `scraper-status` snapshots. |
| `templates/index.html`, `index3.html`, `index4.html`, `indexa.html` | Angular build output committed under `templates/` (`data-critters-container`). Dead. |
| `templates/index2.html` | Older server-rendered page using `url_for('static', ...)`. No route renders it. |
| `static/` | **Gitignored Angular build output.** Contains `index.html`, `main-*.js`, `polyfills-*.js`, `scripts-*.js`, `styles-*.css`, `assets/` (copied from `adminpro/src/assets`), `media/` (assets the builder hashes because CSS references them) and `3rdpartylicenses.txt`. Fully reproducible from tracked sources — verified file by file before it was untracked. A clean clone has none of it. |
| `supermami.json` (repo root) | A 368 KB scrape artifact that is tracked despite `*.json` being ignored. Reference data, not runtime input — no code reads it (the legacy routes that wanted sibling filenames were deleted, K-11). |

## 9. File index

| File | Purpose |
| --- | --- |
| `app.py` | `create_app()` factory: CORS, sockets, Mongo, services, blueprints |
| `main.py` | WSGI entry point (`gunicorn main:app`) |
| `api/config.py` | `Settings` (frozen dataclass) from the environment |
| `api/container.py` | `Services` composition root (`app.extensions['lalistita']`) |
| `api/blueprints/frontend.py` | `/` SPA root + `/scrape` registry-generated monitor page |
| `api/blueprints/products.py` | `/supermercados` HTTP shell + fallback |
| `api/blueprints/scrapers.py` | `/api/scrapers` control API |
| `api/blueprints/legacy.py` | registry-generated `/scraping-<slug>` aliases |
| `api/cli.py` | `python -m api.cli list\|run` — scraper runner without Flask |
| `api/services/products.py` | `ProductService.catalog()` — grouping/dedupe/sort/counts |
| `api/services/scraping.py` | `ScraperManager` — runs, stop, status snapshots |
| `api/sockets.py` | `socketio` singleton, `configure_sockets()`, `SocketIOReporter` |
| `api/helpers.py` | `remove_duplicates_by_key()`, `name_parse()` |
| `api/repositories/products.py` | `ProductRepository` port + Mongo adapter |
| `api/scrapers/base.py` | `BaseScraper` + `ScrapeContext` contract |
| `api/scrapers/registry.py` | `ScraperRegistry` + `default_registry()` (all five) |
| `api/scrapers/errors.py` | `ScraperError` family |
| `api/scrapers/browser.py` | `build_chrome(settings)` — the only driver factory |
| `api/scrapers/http.py` | shared HTTP session with the legacy User-Agent |
| `api/scrapers/{supermami,hiperlibertad,disco,carrefour,changomas}.py` | the five ported scrapers |
| `api/models/productos.py` | Dead (mongoengine APIs against pymongo) |
| `adminpro/src/app/pages/dashboard/` | Main ag-grid view |
| `adminpro/src/app/service/app.service.ts` | Single HTTP call to the API |
| `docs/agent-context/runbook.md` | How to run everything |
| `docs/agent-context/known-issues.md` | Defect register |
