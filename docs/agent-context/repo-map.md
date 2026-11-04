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
                            │  blueprint `app_file2`
                    ┌───────▼─────────────────────┐
                    │  api/routes.py              │
                    └──┬────────┬────────┬────────┘
                       │        │        │
         send_from_dir │        │        │ Thread(...)
         (static/)     │        │        └──────────────► api/scrapers/*.py
                       │        │                             │  Selenium
                       │        │                             ▼
                       │        │                        notifyStatus(...)
                       │        │                             │
                       │        │        ┌────────────────────┘
                       │        │        ▼
                       │        │   api/sockets.py  SocketIO.emit
                       │        │        │
                       │        │        ▼
                       │        │   templates/scrape.html  (live monitor)
                       │        │
                       │        └──► Mongo: lalistitadev.productos
                       ▼
              static/index.html  (Angular 19 bundle, committed)
```

## 2. Bootstrap — `app.py` (46 lines)

| Line | What happens | Consequence |
| --- | --- | --- |
| `app.py:11` | `load_dotenv()` | `.env` is optional; absent → defaults kick in |
| `app.py:13` | `Flask(__name__, static_url_path='')` | `static/` is served at the URL root |
| `app.py:15` | `CORS(app)` | every origin allowed, including scraper-control POSTs |
| `app.py:18` | `SECRET_KEY = 'secret!'` | hardcoded; fine only because no auth session is implemented |
| `app.py:22` | `app.register_blueprint(app_file2)` | all routes come from `api/routes.py` |
| `app.py:26` | `configure_sockets(app)` | **inside `if __name__ == '__main__'`** → SocketIO uninitialized under gunicorn |
| `app.py:32,42` | `app.mongodb_client = MongoClient(...)` | **inside `__main__`** → `current_app.mongodb_client` missing under gunicorn |
| `app.py:33,43` | `app.database = client["lalistita"]` | dead: consumers use `lalistitadev` |
| `app.py:36` | `app.run(port=3000, debug=True)` | development server as the default runtime |
| `app.py:46` | `app.run(port=int(PORT), debug=True)` | `debug=True` also in the "production" branch |

`configure_routes(app)` exists only as a commented-out alternative
(`api/routes.py:15`); the blueprint path is the live one.

## 3. Endpoints — `api/routes.py`

Blueprint name: `app_file2`.

| Method | Path | Handler | Real behavior |
| --- | --- | --- | --- |
| GET | `/` | `root` (`:21`) | `send_from_directory(static, index.html)` |
| GET | `/scrape` | `scrape` (`:26`) | renders `templates/scrape.html` (the only live template) |
| POST | `/scraping-disco` | `scrapingDisco` (`:30`) | **broken**: `Thread(target=scrape_disco(categoria),)` runs inline, then `Thread(target=None).start()` raises |
| POST | `/scraping-hiperlibertad` | `scrapingHiperlibertad` (`:38`) | **blocking**: no thread, request waits for the full scrape |
| POST | `/scraping-supermami` | `scrapingSupermami` (`:46`) | **blocking**: no thread |
| GET | `/scraping-supermami-stop` | `scrapingSupermamiStop` (`:53`) | returns `None` → Flask 500 |
| POST | `/scraping-carrefour` | `scrapingCarrefour` (`:58`) | correct: `Thread(target=..., args=(categoria,))` |
| POST | `/scraping-changomas` | `scrapingChangomas` (`:65`) | thread + private asyncio loop for the `async def` scraper |
| GET | `/scraping-changomas-stop` | `scrapingChangomasStop` (`:84`) | returns `None` → Flask 500 |
| GET | `/supermercados` | `ReturnJSON` (`:89`) | reads `lalistitadev.productos`, groups, dedupes, sorts |
| GET | `/supermercado-carrefour` | `:150` | opens `carrefour.json` (absent, gitignored) → 500; ignores the data anyway |
| GET | `/supermercado-disco` | `:159` | same, `disco.json` |
| GET | `/supermercado-hiper` | `:168` | same, `hiperlibertad.json` |
| GET | `/supermercado-supermami` | `:177` | same, `supermami.json` |

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
(`api/routes.py:106-115`): `disco`, `carrefour`, `hiper*`, `mami*`. **ChangoMás
has no branch**, so its products never appear. Dedupe is
`remove_duplicates_by_key(list, 'name')` — first occurrence wins
(`api/helpers.py:3`). On any exception the route returns an empty payload plus
an `error` key rather than failing loudly (`api/routes.py:137-147`).

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
| Database actually used | `lalistitadev` (`api/routes.py:94`, all scrapers) |
| Database set but unused | `lalistita` (`app.py:33,43`) |
| Collection | `productos` |
| Access pattern | raw `pymongo` — `find`, `insert_many`, `delete_many`; no ODM, no indexes, no migrations |
| Env var | `MONGODB_URI`; local fallback `mongodb://localhost:27017/` |

## 6. Frontend — `adminpro/`

- Angular **19.2.19**, **NgModule-based** (`app.module.ts`,
  `app-routing.module.ts`) — the standalone-migration flags are `standalone:
  false`, deliberate, from the PR #18 migration.
- Build system: `@angular-devkit/build-angular:application`;
  `outputPath: { base: "../static", browser: "" }` (`angular.json:16-19`) →
  output lands directly in the repo's committed `static/`.
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
| `templates/scrape.html` | The only rendered template (`api/routes.py:26`). Loads SocketIO 4.0.1 from cdnjs and subscribes to `scraping-message-<supermarket>` channels. |
| `templates/index.html`, `index3.html`, `index4.html`, `indexa.html` | Angular build output committed under `templates/` (`data-critters-container`). Dead. |
| `templates/index2.html` | Older server-rendered page using `url_for('static', ...)`. No route renders it. |
| `static/` | Committed Angular build: `index.html`, `main-*.js`, `polyfills-*.js`, `scripts-*.js`, `styles-*.css`, plus `assets/` and `media/`. Rebuilding adds new hashes and leaves the old ones behind. |
| `supermami.json` (repo root) | A 368 KB scrape artifact that is tracked despite `*.json` being ignored. Reference data, not runtime input — the routes that read `*.json` want other filenames. |

## 8. File index

| File | Purpose |
| --- | --- |
| `app.py` | Flask app, CORS, blueprint, Mongo, dev server |
| `api/routes.py` | All HTTP endpoints |
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
