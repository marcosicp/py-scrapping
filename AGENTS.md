# AGENTS.md

Canonical context for any AI agent working in this repository. Read this before
reading code. It is deliberately short; the depth lives in
[`docs/agent-context/`](docs/agent-context/).

**Scope of truth:** verified against `main@06b37b7`. If a command here fails, the
document is wrong and fixing it is part of your task, not an optional cleanup.

---

## 1. What this project is

**LaListita** — an Argentine supermarket price comparer. Selenium scrapers pull
product data from five chains (Disco, Carrefour, ChangoMás, HiperLibertad,
SuperMami), the data lands in MongoDB, a Flask API serves it, and Angular 21
renders it in a dashboard.

```
Browser ──► Flask (app.py, port 3000)
              ├── Blueprint  api/routes.py      REST + scraper control
              ├── SocketIO   api/sockets.py     live scraper progress → /scrape
              ├── Scrapers   api/scrapers/*.py   Selenium + JSON-LD / JSON API
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
   is stale in specific ways listed in §7. Correct the README.
5. **A pytest suite exists in `tests/`** (see §8). Never claim a result you did
   not observe — run it, or say you did not run it.
6. **ChromeDriver is a hardcoded absolute path.** `/usr/local/bin/chromedriver-141`
   appears in four of the five scrapers. Scrapers cannot run without a driver
   matching the installed Chrome.
7. **Do not start a scraper against production data casually.** Carrefour's
   `save_to_mongodb` does `delete_many(...)` before `insert_many(...)`
   (`api/scrapers/scrap_carrefour.py:43`). It replaces, it does not append.
8. **`main` is the default branch.** Branch before writing code.

## 3. Stack — reality vs. what documents claim

| Layer | Real (verified) | Claimed elsewhere |
| --- | --- | --- |
| Python (all targets) | **3.15.2** — `.python-version`, `runtime.txt`, `Dockerfile:4`, `app.yaml`, CI | README says 3.11 (stale) |
| Python (local venv) | 3.15.2, created from the python.org installer | — |
| Flask | 3.0.0 | — |
| Realtime | flask-socketio 5.3.6 | — |
| DB driver | pymongo 4.6.0 (raw, no ODM) | — |
| Scraping | selenium 4.15.2, requests-html 0.10.0, beautifulsoup4 4.12.2 | — |
| Frontend | **Angular 21.2.x**, NgModule-based, Material 21.x, ag-grid 32.3.9, TypeScript 5.9 | README says Angular 16 |
| Server | gunicorn 21.2.0 | — |
| Deploy | three contradicting stories (§7, D-6) | README says Docker + Cloud Run |

## 4. Layout — what is alive and what is dead

```
app.py                  create_app() factory: CORS, SECRET_KEY, blueprint, SocketIO, Mongo
main.py                 WSGI entry point — `gunicorn main:app` uses this
api/config.py           Settings (frozen dataclass) resolved from SECRET_KEY/MONGODB_*
api/container.py        Services composition root: init_services/get_services (app.extensions['lalistita'])
api/blueprints/         frontend.py (`/`, `/scrape`) + products.py (`/supermercados`) + scrapers.py (`/api/scrapers` control API) + legacy.py (registry-generated `/scraping-<slug>` aliases); HTTP layer only
api/services/           products.py — ProductService.catalog(): grouping/dedupe/count logic
api/routes.py           Scraper-control routes and the dead `/supermercado-*` routes only (being replaced) (blueprint `app_file2`)
api/sockets.py          SocketIO singleton + notifyStatus(channel, message) + SocketIOReporter (scraper progress publisher)
api/helpers.py          remove_duplicates_by_key(), name_parse() → {name, unidad}
api/scrapers/*.py       One class per supermarket, uniform start/stop contract
api/scrapers/base.py    Scraper contract: BaseScraper (slug/label/categories/run(ctx)) + ScrapeContext (report, should_stop, sleep, save, browser(), http)
api/scrapers/browser.py Chrome factory: build_chrome(settings) driven by CHROMEDRIVER_PATH / CHROME_HEADLESS (D8); Selenium imported lazily
api/scrapers/registry.py ScraperRegistry (explicit registration, slug validation) + default_registry()
api/scrapers/errors.py   ScraperError family: UnknownScraper, InvalidCategory, AlreadyRunning, NotRunning
api/scrapers/http.py     Shared HTTP session with the legacy browser User-Agent (no requests-html)
api/services/scraping.py ScraperManager + RunStatus/RunState (per-supermarket runs: threads, single-flight, cooperative stop)
api/repositories/       ProductRepository port + Mongo adapter (replace inserts before deleting)
tests/                  pytest suite (settings + app factory; no network, no DB, no Chrome)
adminpro/src/app/       Angular 21 source (dashboard, login, register, progress, grafica1)
templates/scrape.html   The ONLY template a route renders (SocketIO monitor)
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
| `/supermercado-carrefour`, `/supermercado-disco`, `/supermercado-hiper`, `/supermercado-supermami` | `api/routes.py:150-184` open absent gitignored JSON files, then ignore the data and return `static/index.html`. |
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

# Frontend dev server (bypasses the bundle entirely)
cd adminpro && npm start             # ng serve on :4200
```

Note: `adminpro/angular.json:16` sets `outputPath` to `{ "base": "../static",
"browser": "" }`, so `ng build` writes **straight into `static/`**, which is
bookkeeping-free precisely because `static/` is gitignored. A build no longer
produces a diff; only source changes do.

## 6. Scraper contract

New scrapers implement `BaseScraper` (`api/scrapers/base.py`) and receive a
`ScrapeContext` in `run(ctx)`. **SuperMami is already ported**:
`api/scrapers/supermami.py` is the first port (T7) and the pattern the rest
follow. The legacy shape below still describes the remaining unported
scrapers (T8-T11 in `odd/tasks/backend-architecture.md`).

Every legacy scraper follows the same shape; preserve it when adding a
supermarket to it.

```python
class ScrapeX:
    activeX = True                    # stop flag
    def scrape_x_stop(self): ...      # sets flag False
    def scrape_x(self, categoria):    # hardcoded subcategory list
        notifyStatus("scraping-message-x", "...")   # progress → /scrape
    def save_to_mongodb(self, jsonData, category_name): ...
```

- Subcategories are **hardcoded lists**, not discovered. `?category=` only
  matches `"almacen"`. Adding a category means editing the list in the scraper.
- SuperMami, being ported, is no longer in this shape: it persists through
  `ProductRepository.replace_products` (insert first, then prune — never the
  legacy `delete_many` + `insert_many`), reports over `ctx.report` and saves
  with `ctx.save`.
- Collected record shape: `supermercado`, `name`, `unidad` (split out by
  `name_parse`), `brand`, `sku` (absent for SuperMami), `price`; then
  `save_to_mongodb` adds `scraped_at` (UTC) and `categoria` (+ `subcategoria` for
  HiperLibertad).
- Disco/Carrefour/SuperMami parse embedded JSON-LD (`itemListElement`).
  HiperLibertad hits the VTEX `api/catalog_system/pub/products/search` JSON API
  using cookies harvested by a headless driver. ChangoMás is `async def` and the
  route wraps it in its own event loop.
- `requests-html`'s `arender()` is **non-functional** on Python ≥3.10 — four of the
  five scrapers depend on it. See known-issues K-18. Any scraping task must
  confront this first; do not assume the scrapers work.
- **SuperMami has no Selenium driver at all.** It imports selenium modules it
  never uses and scrapes with `requests_html` only (`arender(sleep=4)`), and its
  pagination loop is capped at 2 pages by a literal `range(1, 3)`
  (`api/scrapers/scrap_supermami.py:54`) even though it computes `totalPages`.
- **ChangoMás never writes to MongoDB** — it dumps `.changomas/almacen/*.json`
  (`api/scrapers/scrap_changomas.py:147`). Its data never reaches the API, and
  `/supermercados` has no changomas branch.

## 7. Traps (each one costs a first-time agent 10+ minutes)

**T-1 · `adminpro/node_modules` is absent.** `ng serve`/`ng build` fail until
`npm install` runs inside `adminpro/`.

**T-2 · Two scraper routes are not async and one is doubly wrong.**
`/scraping-disco` does `Thread(target=scrape_disco(categoria),)` — the call
executes inline, then `Thread(target=None)` raises on `.start()`. The request
blocks for the whole scrape and then 500s. `/scraping-hiperlibertad` and
`/scraping-supermami` call the scraper synchronously with no thread at all.

**T-3 · Deploy stories contradict each other.** `Dockerfile` CMD runs
`gunicorn ... main:app` but **`main.py` does not exist** — the image builds and
then crashes. `Procfile` runs `python app.py` with `debug=True`.
`gunicorn_config.py` is orphaned. `app.yaml` (App Engine) and `manifest.yml`
(Cloud Foundry, 128 MB — too small for Chrome) are leftovers.

**T-5 · Hardcoded secrets and hosts.** `DEFAULT_SECRET_KEY = 'secret!'`
(`api/config.py`) is the fallback for `SECRET_KEY`. `adminpro/src/app/service/app.service.ts:21` hardcodes
`http://127.0.0.1:3000/supermercados` — there is no `environments/` directory, so
the production API base URL cannot be configured per build.

**T-6 · ChromeDriver 141 is an absolute path.** `Service('/usr/local/bin/chromedriver-141')`
in four of the five scrapers. Mismatch with the installed Chrome silently breaks
scraping. Separately, `requests-html`'s `arender()` (Disco, Carrefour,
ChangoMás, SuperMami) downloads its own Chromium on first use — a second,
independent browser dependency.

**T-7 · `*.json` is globally gitignored** (rule 2 above). Highest-frequency
self-inflicted mistake in this repo.

**T-8 · Duplicate imports and dead code** are normal here (e.g. `from threading
import Thread` twice in `api/routes.py:1,6`). Do not assume an unused import
means the surrounding block is live; read the route registration.

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
- `webdriver-manager` is a declared dependency but every scraper bypasses it.

Consequence: watched behavior is covered by the pytest suite, but **live
scraping is still verified manually** — the scrapers need Chrome, the pinned
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
