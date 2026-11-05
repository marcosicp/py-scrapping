# AGENTS.md

Canonical context for any AI agent working in this repository. Read this before
reading code. It is deliberately short; the depth lives in
[`docs/agent-context/`](docs/agent-context/).

**Scope of truth:** verified against `feat/backend-architecture@30b20cb` (T1-T14a
of the backend architecture are committed). If a command here fails, the
document is wrong and fixing it is part of your task, not an optional cleanup.

---

## 1. What this project is

**LaListita** — an Argentine supermarket price comparer. Selenium scrapers pull
product data from five chains (Disco, Carrefour, ChangoMás, La Anónima,
SuperMami), the data lands in MongoDB, a Flask API serves it, and Angular 21
renders it in a dashboard.

```
Browser ──► Flask (app.py, port 3000)
              ├── Blueprints api/blueprints/    REST + scraper control + SPA root
              ├── SocketIO   api/sockets.py     live scraper progress → /scrape
              ├── Scrapers   api/scrapers/*.py  BaseScraper contract + Selenium / JSON-LD / JSON API
              └── Mongo      lalistitadev.productos
                             ▲
              Angular 21 (adminpro/src) ── build ──► static/ ── served by Flask
```

## 2. Hard rules

1. **`static/` is build output and is NOT versioned.** It is gitignored; a
   fresh clone has no bundle and `/` answers **503** with the build command. Build
   it with `cd adminpro && npm ci && npm run build`. Never hand-edit it — the
   source of truth is `adminpro/src/`, and every file in it is reproducible from
   there (verified file by file).
2. **Never add a `.json` file without checking `.gitignore` first.** It ignores
   `*.json` globally (`.gitignore:56`), with exceptions only for
   `package.json`, `package-lock.json`, `angular.json`, `tsconfig.json`. A new
   config/fixture JSON will be silently untracked. Add an exception or use
   `.jsonc`/`.py`.
3. **Never commit `.env`, `supermami.json` variants containing fresh scrapes, or
   anything under `.disco/ .carrefour/ .changomas/ .hiperlibertad/ .supermami/`.**
4. **Do not "fix" the README to match the code by changing the code.** The README
   is stale in specific ways listed in §3. Correct the README.
5. **A pytest suite exists in `tests/`** (see §8). Never claim a result you did
   not observe — run it, or say you did not run it.
6. **The Chrome driver comes from `api/scrapers/browser.py` (`build_chrome`),
   nowhere else.** `CHROMEDRIVER_PATH` selects the binary; unset (the default),
   Selenium Manager — bundled with selenium 4.6+ — resolves a driver matching
   the installed Chrome, which needs network on first use. Never hardcode a
   driver path in a scraper.
7. **Do not start a scraper against production data casually.** Every save goes
   through `ProductRepository.replace_products`
   (`api/repositories/products.py:42`): it REPLACES the scraper's
   `supermercado`/`categoria` slice (insert first, then prune the old ids; an
   empty scrape is a no-op). It replaces, it does not append.
8. **`main` is the default branch.** Branch before writing code.

## 3. Stack — reality vs. what documents claim

| Layer | Real (verified) | Claimed elsewhere |
| --- | --- | --- |
| Python (all targets) | **3.15.2** — `.python-version`, `runtime.txt`, `Dockerfile:18`, `app.yaml`, CI | README says 3.11 (stale) |
| Python (local venv) | 3.15.2, created from the python.org installer | — |
| Flask | 3.1.3 | — |
| Realtime | flask-socketio 5.7.2 | — |
| DB driver | pymongo 4.19.0 (raw, no ODM) | — |
| Scraping | selenium 4.52.0 (Selenium Manager resolves the driver), beautifulsoup4 4.15.0, lxml 6.1.3; `requests-html`/`webdriver-manager` **removed** (K-18) | — |
| Frontend | **Angular 21.2.x**, NgModule-based, Material 21.x, ag-grid 32.3.9, TypeScript 5.9 | README says Angular 16 |
| Server | gunicorn 26.2.0 | — |
| Deploy | four contradicting stories (§7, D-6) | README says Docker + Cloud Run |

## 4. Layout — what is alive and what is dead

```
app.py                  create_app() factory: CORS, SECRET_KEY, sockets, Mongo, services, blueprints
main.py                 WSGI entry point — `gunicorn main:app` uses this
api/config.py           Settings (frozen dataclass) resolved from SECRET_KEY/MONGODB_*/CHROMEDRIVER_PATH/CHROME_HEADLESS
api/container.py        Services composition root: init_services/get_services (app.extensions['lalistita'])
api/blueprints/         frontend.py (`/`, `/scrape` — the monitor page is registry-generated) + products.py (`/supermercados`) + scrapers.py (`/api/scrapers` control API) + legacy.py (registry-generated `/scraping-<slug>` aliases); HTTP layer only
api/cli.py              `python -m api.cli` scraper runner: `list` + `run <slug>`, no Flask/gunicorn
api/services/           products.py — ProductService.catalog(): grouping/dedupe/count logic
                        scraping.py — ScraperManager + RunStatus/RunState (per-supermarket runs: threads, single-flight, cooperative stop)
api/sockets.py          SocketIO singleton + SocketIOReporter (scraper progress publisher)
api/helpers.py          remove_duplicates_by_key(), name_parse() → {name, unidad}
api/repositories/       ProductRepository port + Mongo adapter (replace_products inserts before pruning)
api/scrapers/base.py    Scraper contract: BaseScraper (slug/label/categories/run(ctx)) + ScrapeContext (report, should_stop, sleep, save, browser(), http)
api/scrapers/registry.py ScraperRegistry (explicit registration, slug validation) + default_registry() with all five
api/scrapers/errors.py   ScraperError family: UnknownScraper, InvalidCategory, AlreadyRunning, NotRunning
api/scrapers/browser.py Chrome factory: build_chrome(settings) driven by CHROMEDRIVER_PATH / CHROME_HEADLESS (D8); Selenium imported lazily
api/scrapers/http.py    Shared HTTP session with the legacy browser User-Agent (no requests-html)
api/scrapers/           One BaseScraper subclass per supermarket: supermami, laanonima, disco, carrefour, changomas
tests/                  pytest suite (363 passed / 9 skipped by default; no network, no DB, no Chrome)
adminpro/src/app/       Angular 21 source (dashboard, login, register, progress, grafica1)
templates/scrape.html   The ONLY template a route renders (self-contained admin panel: own CSS, no third-party asset, polls /api/scrapers; registry-generated)
docs/agent-context/     Deep dives for agents — read when you need detail
odd/tasks/              ODD feature documents
static/                 Angular build output — GITIGNORED, build it locally
```

**Dead / do not extend without deciding first:**

| Path | Why it is dead |
| --- | --- |
| `api/models/productos.py` | `from pymongo import pymongo` + `pymongo.Document`/`StringField` — those are mongoengine APIs. Imported by nothing. |
| `templates/index.html`, `index3.html`, `index4.html`, `indexa.html` | Angular build output accidentally committed as Jinja templates. Unused. |
| `templates/index2.html` | Legacy server-rendered page. No route renders it. |
| `gunicorn_config.py` | Nothing references it; `Procfile` runs `python app.py` instead. |
| `manifest.yml`, `app.yaml` | Cloud Foundry / App Engine leftovers. |
| `feature/angular-19-migration` | Already squashed into `main` as PR #18. Do not resurrect. |

## 5. Commands

Full runbook with status per command:
[`docs/agent-context/runbook.md`](docs/agent-context/runbook.md).

```bash
# Backend setup — Python 3.15 (.python-version). The venv is already provisioned;
# recreate it only if it is missing or broken.
python3.15 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Tests + flake8 (dev/CI toolchain; safe to run — no network, no DB, no Chrome)
pip install -r requirements-dev.txt

pytest

# CI lint gate (the real one; the second workflow flake8 pass is --exit-zero)
flake8 . --exclude .venv,adminpro,static,node_modules --select=E9,F63,F7,F82 --count

# Frontend bundle — REQUIRED before `/` will answer; static/ is not versioned
cd adminpro && npm ci && npm run build && cd ..

# Run (needs .env with MONGODB_URI)
python app.py                       # http://localhost:3000  (also /scrape)

# Production-shaped entry point — this is what the Docker image runs
gunicorn --bind 127.0.0.1:8124 --workers 1 main:app

# List / run one supermarket scraper from the shell — no Flask, no SocketIO
python -m api.cli list
python -m api.cli run carrefour --category almacen

# Frontend dev server (bypasses the bundle entirely)
cd adminpro && npm start             # ng serve on :4200
```

Note: `adminpro/angular.json:16` sets `outputPath` to `{ "base": "../static",
"browser": "" }`, so `ng build` writes **straight into `static/`**, which is
bookkeeping-free precisely because `static/` is gitignored. A build no longer
produces a diff; only source changes do.

## 6. Scraper contract

Every supermarket scraper implements `BaseScraper`
(`api/scrapers/base.py`) and receives a `ScrapeContext` in `run(ctx)`:

- `ctx.report(text)` — progress; live runs emit it over Socket.IO, the CLI
  prints it, tests assert it.
- `ctx.http` — shared `requests.Session` carrying the legacy browser
  User-Agent (`api/scrapers/http.py`).
- `ctx.browser()` — context manager yielding a Chrome driver built by
  `api/scrapers/browser.py` and quit afterwards.
- `ctx.save(products, categoria=..., subcategoria=...)` — persists through
  `ProductRepository.replace_products` (insert first, then prune; empty scrape
  is a no-op) and stamps `scraped_at` (UTC).
- `ctx.should_stop()` / `ctx.sleep(seconds)` — cooperative stop.

**Adding a supermarket is one module + one `default_registry()` line
(`api/scrapers/registry.py`) + one contract-test pass.** No route, no template
card, no CLI change: the control API, the `/scraping-<slug>` aliases, the
`/scrape` monitor page and `python -m api.cli` are all generated from the
registry.

Quirk inventory — behaviours that look odd and must be validated against a
real run before anyone "fixes" them, plus the site facts a future change must
not undo (details in
[`docs/agent-context/known-issues.md`](docs/agent-context/known-issues.md)):

- **Disco reads the VTEX catalog API, never the HTML or a browser.** The
  subcategories are the children of `almacen` discovered from
  `/api/catalog_system/pub/category/tree/2` and the products come from
  `/api/catalog_system/pub/products/search/<path>` in 50-item windows. That API
  answers **400 for any window beyond item 2550** (`_from=2501` and
  `_to=2550`), so a node bigger than that (almacén totals 39 220 products) is
  bisected with `fq=P:[lo TO hi]` price ranges. Do not "simplify" it into one
  flat paged crawl or bump `MAX_WINDOW`: the tail of the big nodes would 400
  and fail the run.
- **Carrefour reads the VTEX catalog API, never the HTML.** `/almacen` is a
  4.7 MB VTEX shell with no JSON-LD; the products come from
  `/api/catalog_system/pub/products/search`. That API answers **400 for
  `_from=2501`**, and almacén holds 6188 products, so the run walks the level-2
  categories discovered from `/api/catalog_system/pub/category/tree/2` (whose
  children partition the parent exactly). Do not "simplify" it into one flat
  paged crawl: the last ~1400 products would silently vanish.
- **ChangoMás re-fetches the discovery page in its page loop**
  (`api/scrapers/changomas.py:152`) and is persisted but still not shown by
  `/supermercados` (K-12, API half open).
- **SuperMami is Oracle Endeca, not VTEX** and no longer caps pages
  (`api/scrapers/supermami.py`). The category is resolved from the site menu
  and the products come from `/super/categoria/<slug>/_/N-<id>` with
  `No=` / `Nrpp=500`, read from the page's embedded `gtag('event',
  'view_item_list', …)` JSON: `Nrpp` scales and there is **no offset
  ceiling**, so `almacen`'s 3 210 products take seven requests and are
  collected whole. The **parent is the category scope on purpose**: its 15
  level-2 children sum 2 680 against the parent's 3 210, so descending to
  children would lose 530 products — the opposite of Carrefour/Disco. Do not
  re-add a page cap or a children walk.

## 7. Traps (each one costs a first-time agent 10+ minutes)

**T-1 · `adminpro/node_modules` is absent.** `ng serve`/`ng build` fail until
`npm install` runs inside `adminpro/`.

**T-3 · Deploy stories contradict each other.** `Dockerfile` CMD runs
`gunicorn ... main:app` and `main.py` now exists, so the image entry point is
coherent (K-5). `Procfile` still runs `python app.py` with `debug=True` — a
dev server in production. `gunicorn_config.py` is orphaned. `app.yaml`
(App Engine) and `manifest.yml` (Cloud Foundry, 128 MB — too small for Chrome)
are leftovers.

**T-5 · Hardcoded secrets and hosts.** `DEFAULT_SECRET_KEY = 'secret!'`
(`api/config.py`) is the fallback for `SECRET_KEY`. `adminpro/src/app/service/app.service.ts:21` hardcodes
`http://127.0.0.1:3000/supermercados` — there is no `environments/` directory, so
the production API base URL cannot be configured per build.

**T-7 · `*.json` is globally gitignored** (rule 2 above). Highest-frequency
self-inflicted mistake in this repo.

**T-9 · `tsconfig` must keep bundler module resolution.** `@angular/common@21`
no longer ships physical subpath directories, so `"moduleResolution": "node"`
(Node10) cannot resolve `@angular/common/http` and the build dies with `TS2307`.
Keep the pair `"moduleResolution": "bundler"` and `"module": "preserve"`.
Don't revert it to `"node"` to "fix" an unrelated resolution error.

**T-10 · SocketIO runs in `threading` async mode.** Neither `eventlet` nor `gevent`
is installed, so `async_mode` resolves to `threading`: realtime works over HTTP
long-polling, and the WebSocket *transport upgrade* is not available. Do not
"fix" this by adding a worker class without first removing `threading` from the
picture — and note `gunicorn_config.py` is orphaned, so it changes nothing.

**T-11 · Angular 21 no longer enables zone-driven change detection by itself.**
The app boots with `platformBrowserDynamic().bootstrapModule(AppModule)`. Since
the v21 migration that bootstrap does not render async updates: an
`HttpClient` response assigns to the component and no render is ever scheduled,
so `/#/dashboard` shows its layout with **no data** and no console error.
`AppModule.providers` must include
`provideZoneChangeDetection({ eventCoalescing: true })`; it is easy to delete as
"redundant" and impossible to notice without a browser, because `adminpro` has
**zero `*.spec.ts` files**. The diagnostic that found it: in `ng serve` (dev
mode) `window.ng.getComponent(el).items` is populated while the DOM stays empty,
and `ng.applyChanges(component)` renders it. Full record:
`odd/tasks/angular-21-change-detection.md`.

## 8. Testing reality

- Python: a pytest suite lives in `tests/`. Install the dev toolchain and run
  it with `pip install -r requirements-dev.txt && pytest` (`pytest.ini` already
  points at `tests/`). No test touches the network, Chrome or a real database
  (the Mongo fixtures use an unroutable URI), with one opt-in exception: the
  repository integration tests run against a real MongoDB only when
  `MONGODB_TEST_URI` is set, always on a throwaway `lalistita_test_<random>`
  database that the fixture creates and drops (and refuses to drop anything
  whose name does not start with `lalistita_test_`).
- Angular: karma + jasmine are configured in `adminpro/package.json` and
  `tsconfig.spec.json` exists, but there are **zero `*.spec.ts` files**.

Default run: **363 passed, 9 skipped** — the 9 skips are the opt-in MongoDB
integration tests.

Consequence: watched behavior is covered by the pytest suite, but **live
scraping is still verified manually** — the scrapers need Chrome, a matching
driver and a real database, none of which any test exercises. When you change
behavior, state exactly how you verified it (which test, which endpoint, which
log line, which UI path) and never assert a result you did not observe.

## 9. Conventions

- Backend code, comments, commit messages, and these docs: **English**. Existing
  Spanish strings in scrapers and the UI are legacy; do not translate them
  opportunistically.
- Comments use `# -- ...` and `# -- append item to json` style in scrapers; match
  the file you are editing rather than imposing the style of another.
- Commit messages follow Conventional Commits (`chore:`, `fix:`, `feat:`) — see
  `git log` for the established set.
- Never reformat a file you are not otherwise changing.

## 10. Where to go deeper

| Need | Read |
| --- | --- |
| Request flow, every endpoint, data schema, scraper internals | [`docs/agent-context/repo-map.md`](docs/agent-context/repo-map.md) |
| How to actually install, run, build, deploy — with per-command status | [`docs/agent-context/runbook.md`](docs/agent-context/runbook.md) |
| Every defect found, with severity and causality | [`docs/agent-context/known-issues.md`](docs/agent-context/known-issues.md) |
| Work in progress for this doc set | [`odd/tasks/agent-context-bootstrap.md`](odd/tasks/agent-context-bootstrap.md) |

## 11. Maintaining this file

`AGENTS.md` is the single source of truth. `CLAUDE.md` and
`.github/copilot-instructions.md` are pointers to it, on purpose, to make drift
impossible.

Update this file when you change: the stack, the run/build commands, the deploy
path, the Mongo database or collection name, or the scraper contract. If you fix
one of the traps in §7, delete it from §7 and note the fix in the commit message.
Do not add prose that already exists in `docs/agent-context/` — link instead.
