# Repository map

Deep reference for the LaListita codebase. Verified against `main@06b37b7`.
Entry point for agents is [`AGENTS.md`](../../AGENTS.md); this file is the detail
behind it.

---

## 1. Request flow

```
                    ┌─────────────────────────────┐
  browser ─────────►│  Flask  app.py :3000        │
                    │  CORS(app) ─ everything     │
                    └───────┬─────────────────────┘
                            │  blueprints `app_file2`, frontend, products
                    ┌───────▼─────────────────────┐
                    │  api/blueprints/*.py        ├─► api/container.py (Services)
                    │  api/routes.py              │
                    └──┬──────┬────────┬──────────┘
                       │      │        │
         send_from_dir │      │        └──► ProductService → api/repositories/products.py
         (static/)     │      │             → Mongo: lalistitadev.productos
                       │      │ Thread(...)
                       │      └────────────────► api/scrapers/*.py
                                                     │  Selenium
                                                     ▼
                                                notifyStatus(...)
                                                     │
                                     ┌───────────────┘
                                     ▼
                            api/sockets.py  SocketIO.emit
                                     │
                                     ▼
                            templates/scrape.html  (live monitor)
                       ▼
              static/index.html  (Angular 21 bundle — gitignored, built locally)
```

## 2. Bootstrap — application factory

`app.py` exposes `create_app()`. Two entry points share it:

| Entry point | Used by | Server |
| --- | --- | --- |
| `python app.py` | local development | Werkzeug, `debug=True` |
| `gunicorn main:app` | Docker and any WSGI host | `main.py` calls `create_app()` at import |

| Step | Where | What happens |
| --- | --- | --- |
| `load_dotenv()` | module scope | `.env` optional; defaults apply without it |
| `Flask(__name__, static_url_path='')` | `create_app` | `static/` is served at the URL root |
| `CORS(app)` | `create_app` | every origin allowed, including scraper-control POSTs (K-13) |
| `SECRET_KEY` | `create_app` | `os.getenv('SECRET_KEY', 'secret!')` — configurable, same default (K-13) |
| `register_blueprint` | `create_app` | scraper routes from `api/routes.py`, the rest from `api/blueprints/` |
| `init_services` | `create_app` | `Services` in `app.extensions['lalistita']`; tests inject a repository |
| `configure_sockets` | `create_app` | SocketIO initialized for **every** entry point (K-1) |
| `_init_mongo` | `create_app` | `MongoClient` + `app.database` (K-2, K-3) |

Three properties worth knowing:

- **Nothing is wired at import time in `app.py`.** `main.py` builds the
  module-level `app` WSGI servers expect. `gunicorn app:app` no longer works;
  use `main:app`.
- **`MongoClient` is lazy**, so importing the app opens no socket and cannot
  hang a worker boot.
- **Mongo config:** `MONGODB_URI` (default `mongodb://localhost:27017/`) and
  `MONGODB_DB` (default `lalistitadev`).
- **`async_mode` is `threading`** — no `eventlet`/`gevent` in the tree — so
  realtime works over long-polling, not over a WebSocket upgrade.

`configure_routes(app)` exists only as a commented-out alternative
(`api/routes.py:10`); the blueprint path is the live one.

## 3. Endpoints

Three blueprints share the URL map: `app_file2` (scraper control + dead alias
routes, `api/routes.py`), `frontend` and `products` (`api/blueprints/`),
all HTTP shells over services.

### `api/routes.py` — scraper control and dead aliases (blueprint `app_file2`)

| Method | Path | Handler | Real behavior |
| --- | --- | --- | --- |
| POST | `/scraping-disco` | `scrapingDisco` (`:16`) | **broken**: `Thread(target=scrape_disco(categoria),)` runs inline, then `Thread(target=None).start()` raises |
| POST | `/scraping-hiperlibertad` | `scrapingHiperlibertad` (`:25`) | **blocking**: no thread, request waits for the full scrape |
| POST | `/scraping-supermami` | `scrapingSupermami` (`:33`) | **blocking**: no thread |
| GET | `/scraping-supermami-stop` | `scrapingSupermamiStop` (`:41`) | returns `None` → Flask 500 |
| POST | `/scraping-carrefour` | `scrapingCarrefour` (`:45`) | correct: `Thread(target=..., args=(categoria,))` |
| POST | `/scraping-changomas` | `scrapingChangomas` (`:52`) | thread + private asyncio loop for the `async def` scraper |
| GET | `/scraping-changomas-stop` | `scrapingChangomasStop` (`:76`) | returns `None` → Flask 500 |
| GET | `/supermercado-carrefour` | `:80` | opens `carrefour.json` (absent, gitignored) → 500; ignores the data anyway |
| GET | `/supermercado-disco` | `:89` | same, `disco.json` |
| GET | `/supermercado-hiper` | `:98` | same, `hiperlibertad.json` |
| GET | `/supermercado-supermami` | `:107` | same, `supermami.json` |

### `api/blueprints/` — frontend and products

| Method | Path | Handler | Real behavior |
| --- | --- | --- | --- |
| GET | `/` | `frontend.root` | `send_from_directory(static, index.html)`; **503 with the build command** when the bundle is absent |
| GET | `/scrape` | `frontend.scrape` | renders `templates/scrape.html` (the only live template) |
| GET | `/supermercados` | `products.supermercados` | `ProductService.catalog()` through the `ProductRepository` (Mongo `lalistitadev.productos`); any exception → empty payload + `error` key, HTTP 200 |

### `api/blueprints/` — scraper control (`/api/scrapers`)

Body shape of every status entry: `{**status.to_dict(), "categories": [...]}` (snapshot of `ScraperManager`).

| Method | Path | Success | Error codes |
| --- | --- | --- | --- |
| GET | `/api/scrapers` | 200 `{"scrapers": [...]}` | — |
| GET | `/api/scrapers/<slug>` | 200 status + categories | `unknown_scraper` (404) |
| POST | `/api/scrapers/<slug>/start` | 202 status + categories | `unknown_scraper` (404), `invalid_category` (400, with `allowed`), `already_running` (409) |
| POST | `/api/scrapers/<slug>/stop` | 202 status + categories | `unknown_scraper` (404), `not_running` (409) |

Error bodies are `{"error": ..., "code": ...}`. `/scraping-<slug>` and `/scraping-<slug>-stop` are thin deprecated POST/GET+POST aliases of these endpoints, generated from the registry (registered slugs only): they return `{"success": true}` on 200 and the same status codes with `{"success": false, ...}` otherwise — unlike the old `/scraping-*` routes in `api/routes.py` (below, still served for the not-yet-ported scrapers) they never block the request and never run a second copy of the same scraper.

There is **no** Disco stop route, no auth, no pagination, no filtering, and no
write API other than "start a scraper".

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
(`api/services/products.py`, first match wins): `disco`, `carrefour`, `hiper*`,
`mami*`. **ChangoMás has no branch**, so its products never appear. Dedupe is
`remove_duplicates_by_key(list, 'name')` — first occurrence wins
(`api/helpers.py:3`). On any exception the blueprint returns an empty payload
plus an `error` key rather than failing loudly (`api/blueprints/products.py`).

## 4. Scrapers — `api/scrapers/`

Uniform shape: a class, an `active<Name>` stop flag, a `*_stop()` setter, a
`scrape_*()` entry point, `notifyStatus()` progress, and
`save_to_mongodb(jsonData, categoria[, subcategoria])`.

| Scraper | Technique | Pages | Persists to | Notes |
| --- | --- | --- | --- | --- |
| `scrap_disco.py` | Selenium nav + `requests_html` `arender(sleep=8)` + JSON-LD `itemListElement` | 14 hardcoded subcats | Mongo per subcat | `save_to_mongodb` at `:29` |
| `scrap_carrefour.py` | Selenium + JSON-LD, two parse paths | 2 categories / 18 subcats | Mongo per category | **deletes then inserts** per category (`:43`) — destructive replace |
| `scrap_changomas.py` | `async def`, Selenium over `masonline.com.ar` | paginated | **JSON files only** `.changomas/almacen/*.json` (`:147`) | never reaches the API |
| `scrap_hiperlibertad.py` | headless Selenium for cookies, then VTEX JSON API | paginated API | Mongo per subcat | `_scrape_subcategory` at `:124` |
| `scrap_supermami.py` | `requests_html` `arender` + JSON-LD — **no Selenium driver** | 2 pages (hardcoded `range(1, 3)`) | Mongo | no `sku` field; unused selenium imports |

Common details:

- Driver: four of the five scrapers create `webdriver.Chrome(service=Service('/usr/local/bin/chromedriver-141'), options=...)`
  with `--no-sandbox` and `--disable-dev-shm-usage`; only HiperLibertad is
  headless. SuperMami creates no driver — it is pure `requests_html`.
- `requests_html`'s `arender()` (Disco, Carrefour, ChangoMás, SuperMami) drives
  its own bundled Chromium via pyppeteer, downloaded on first use. Disco,
  Carrefour and ChangoMás therefore depend on **two** different browsers.
- Categories: a hardcoded `[{"categoria": "almacen", "subcategorias": [...]}]`
  literal inside each scraper (`scrap_disco.py:87`, `scrap_hiperlibertad.py:71`,
  `scrap_carrefour.py:69` — Carrefour has a second `desayuno-y-merienda` entry).
  The `?category=` query parameter only matches `"almacen"` for Disco and
  HiperLibertad; any other value silently does nothing.
- Duplicate suppression is substring-based and O(n²) per page:
  `if not any(element['name'] in jsonitea['name'] for element in jsondata)`.
- Cleanup is inconsistent: `driver.close()` in `finally` for ChangoMás; other
  scrapers leak the driver on exceptions.

### Record schema

| Field | Source | Notes |
| --- | --- | --- |
| `supermercado` | literal | `Disco` / `Carrefour` / `HiperLibertad` / `SuperMami` |
| `name` | JSON-LD `item.name`, size suffix stripped by `name_parse` | |
| `unidad` | `name_parse` output, e.g. `"500 ml"` | comma-joined when multiple matches |
| `brand` | `item.brand.name` | Hiper uses `.get("brand", "")` |
| `sku` | `item.sku` | absent for SuperMami |
| `price` | `item.offers.lowPrice` | stored as a string |
| `scraped_at` | `datetime.utcnow()` added in `save_to_mongodb` | deprecated in Python 3.12+ |
| `categoria` | the request/subcategory label | |
| `subcategoria` | HiperLibertad only | |

`name_parse` (`api/helpers.py:14`) regex:
`(\d+|X\d+)\s*(kg|kgs|g|gr|grs|ml|mls|m|cc|lt|lts)\b`, case-insensitive.

`api/models/productos.py` is **not** part of the schema — it is mongoengine-style
code against `pymongo` and is imported by nothing.

## 5. Mongo usage

| Concern | Value |
| --- | --- |
| Client injection | `app.mongodb_client`, only set inside `__main__` (`app.py:32,42`) |
| Database actually used | `lalistitadev` (`app.database`, all scrapers) |
| Database set but unused | `lalistita` (`app.py:33,43`) |
| Collection | `productos` |
| Access pattern | raw `pymongo` — `find`, `insert_many`, `delete_many`; no ODM, no indexes, no migrations |
| Env var | `MONGODB_URI`; local fallback `mongodb://localhost:27017/` |

## 6. Frontend — `adminpro/`

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

## 7. Templates and static

| Path | Reality |
| --- | --- |
| `templates/scrape.html` | The only rendered template (`api/blueprints/frontend.py`, `scrape`). Loads SocketIO 4.0.1 from cdnjs and subscribes to `scraping-message-<supermarket>` channels. |
| `templates/index.html`, `index3.html`, `index4.html`, `indexa.html` | Angular build output committed under `templates/` (`data-critters-container`). Dead. |
| `templates/index2.html` | Older server-rendered page using `url_for('static', ...)`. No route renders it. |
| `static/` | **Gitignored Angular build output.** Contains `index.html`, `main-*.js`, `polyfills-*.js`, `scripts-*.js`, `styles-*.css`, `assets/` (copied from `adminpro/src/assets`), `media/` (assets the builder hashes because CSS references them) and `3rdpartylicenses.txt`. Fully reproducible from tracked sources — verified file by file before it was untracked. A clean clone has none of it. |
| `supermami.json` (repo root) | A 368 KB scrape artifact that is tracked despite `*.json` being ignored. Reference data, not runtime input — the routes that read `*.json` want other filenames. |

## 8. File index

| File | Purpose |
| --- | --- |
| `app.py` | Flask app, CORS, blueprint, Mongo, dev server |
| `api/routes.py` | Scraper-control routes and the dead `/supermercado-*` aliases |
| `api/blueprints/frontend.py` | `/` SPA root + `/scrape` monitor page |
| `api/blueprints/products.py` | `/supermercados` HTTP shell + fallback |
| `api/services/products.py` | `ProductService.catalog()` — grouping/dedupe/sort/counts |
| `api/container.py` | `Services` composition root (`app.extensions['lalistita']`) |
| `api/sockets.py` | `socketio` singleton, `notifyStatus()`, `configure_sockets()` |
| `api/helpers.py` | `remove_duplicates_by_key()`, `name_parse()` |
| `api/models/productos.py` | Dead (mongoengine APIs against pymongo) |
| `api/scrapers/scrap_disco.py` | Disco |
| `api/scrapers/scrap_carrefour.py` | Carrefour |
| `api/scrapers/scrap_changomas.py` | ChangoMás (JSON files, not Mongo) |
| `api/scrapers/scrap_hiperlibertad.py` | HiperLibertad (VTEX API) |
| `api/scrapers/scrap_supermami.py` | SuperMami |
| `adminpro/src/app/pages/dashboard/` | Main ag-grid view |
| `adminpro/src/app/service/app.service.ts` | Single HTTP call to the API |
| `docs/agent-context/runbook.md` | How to run everything |
| `docs/agent-context/known-issues.md` | Defect register |
