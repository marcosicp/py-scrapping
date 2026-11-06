# Runbook

Every command an agent needs to install, run, build, and deploy LaListita —
annotated with what was actually verified. Entry point for agents is
[`AGENTS.md`](../../AGENTS.md).

## Status legend

| Mark | Meaning |
| --- | --- |
| ✅ VERIFIED | Executed during the bootstrap session; output recorded below |
| 📖 INFERRED | Read from a file, not executed (needs network, Mongo, or a browser) |
| ⛔ BLOCKED | Cannot work in the current checkout without a prerequisite fix |

Environment measured on macOS, Python 3.15.x, Node 26.x, npm 11.x. Exact patch
versions are deliberately omitted — see the security note at the end of this
file. The scrapers that open a browser need a working local Chrome.

---

## 0. Prerequisites — the state of this checkout

| Item | Measured | Verdict |
| --- | --- | --- |
| `.venv` | Python 3.15.x, provisioned | ✅ working |
| Python target | 3.15.2 pinned in `.python-version`, `runtime.txt`, `Dockerfile`, `app.yaml`, CI | ✅ aligned |
| `static/` bundle | **absent in a fresh clone** — gitignored build output | ⛔ `npm ci && npm run build` |
| `python3` on PATH | still resolves to an older framework build because PATH order wins over `/usr/local/bin` | ⚠️ call `python3.15` explicitly |
| `adminpro/node_modules` | absent in a fresh clone | ⛔ `npm install` required |
| Global `ng` | Angular CLI 14.x, `Node ... (Unsupported)` | ⛔ too old for Angular 21 — use the local CLI |
| ChromeDriver | resolved by Selenium Manager (bundled with selenium); `CHROMEDRIVER_PATH` overrides | ✅ no pinned path |
| `.env` | absent (gitignored) | ⛔ `MONGODB_URI` must be provided |
| Tests | pytest suite in `tests/` (291 passed / 9 skipped by default) | ✅ |

## 1. Backend: the virtualenv

Already provisioned. Recreate it only if it is missing or broken:

```bash
rm -rf .venv
python3.15 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

✅ VERIFIED on Python 3.15.x — installs with no source builds, and
`uvx pip-audit --path .venv/lib/python3.15/site-packages` reports
**no known vulnerabilities**.

Notes that will save you time:

- **`requirements.txt` pins direct dependencies only.** Transitive packages float
  on purpose so security patches arrive without a manual bump. The file used to
  be a full `pip freeze` and accumulated 91 advisories doing exactly that.
- **No driver-manager package is needed.** `requests-html`,
  `lxml_html_clean` and `webdriver-manager` were removed (K-18): selenium's
  bundled Selenium Manager resolves a driver matching the installed Chrome
  (`api/scrapers/browser.py`); `CHROMEDRIVER_PATH` overrides it. Selenium is
  imported lazily, so the app imports without it being exercised.
- **Do not add a bare `bson` requirement** — the standalone PyPI package shadows
  pymongo's bundled `bson` and breaks the driver.

### Run the tests

```bash
source .venv/bin/activate
pip install -r requirements-dev.txt   # runtime deps + pytest + flake8
pytest

# Opt-in MongoDB integration tests (throwaway lalistita_test_<random> database,
# created and dropped around the run; the guard in the fixture refuses to drop
# any database not named lalistita_test_*):
MONGODB_TEST_URI=mongodb://localhost:27017/ .venv/bin/python -m pytest tests/test_product_repository.py -q
```

✅ VERIFIED: `pytest` collects the suite in `tests/` and exits 0 —
**291 passed, 9 skipped** by default. The 9 skips are the opt-in MongoDB
integration tests below. No default test touches the network, Chrome or a real
database — the Mongo fixtures point at an unroutable URI
(`mongodb://127.0.0.1:1/…`), so an accidental connection fails fast instead of
reaching any server. The `flake8` gate used by CI is
`flake8 . --exclude .venv,adminpro,static,node_modules --select=E9,F63,F7,F82 --count`.
Settings (`SECRET_KEY`, `MONGODB_URI`, `MONGODB_DB`, `CHROMEDRIVER_PATH`,
`CHROME_HEADLESS`) are resolved in `api/config.py` (`Settings.from_env`);
`app.py` consumes them via `create_app(settings)`.

## 2. Environment variables

Create `.env` at the repo root (gitignored, never commit):

```env
MONGODB_URI=mongodb+srv://<user>:<password>@<cluster>/<db>?retryWrites=true&w=majority
MONGODB_DB=lalistitadev
SECRET_KEY=<random-string>
PORT=3000
```

| Variable | Default | Notes |
| --- | --- | --- |
| `MONGODB_URI` | `mongodb://localhost:27017/` | read by `Settings.from_env` → `_init_mongo`; the client is always created |
| `MONGODB_DB` | `lalistitadev` | previously hardcoded and, worse, hardcoded to the wrong name (K-3) |
| `SECRET_KEY` | `secret!` | legacy default kept; rotating it for real is K-13 |
| `PORT` | `3000` | `python app.py` reads it in `__main__`; WSGI hosts inject it |
| `CHROMEDRIVER_PATH` | unset → Selenium Manager picks a matching driver (needs network on first use) | read by `Settings.from_env`; honored by the single Chrome factory `api/scrapers/browser.py`, which every browser-using scraper reaches through `ctx.browser()` |
| `CHROME_HEADLESS` | off | opt-in headless: `1`, `true`, `yes`, `on` (case-insensitive, surrounding whitespace ignored) add `--headless=new`; default off preserves the visible browser window |

The URI's own database segment is still ignored — `MONGODB_DB` wins. Collection:
`productos`.

## 3. Run the backend

Local development (Werkzeug, `debug=True`):

```bash
source .venv/bin/activate
python app.py
```

Production-shaped, and exactly what the image runs:

```bash
.venv/bin/gunicorn --bind 127.0.0.1:8124 --workers 1 main:app
```

✅ VERIFIED under gunicorn: `GET /` → 200 with 71993 bytes, `GET /scrape` → 200,
and the Engine.IO handshake returns a valid session — which is the proof that
SocketIO is initialized outside `python app.py` (K-1).

- App: <http://localhost:3000> — serves `static/index.html` from the locally built
  bundle. **If you have not built the frontend, `/` answers 503 with the build
  command** — that is the designed behaviour, not a bug.
- Scraper monitor: <http://localhost:3000/scrape>
- API probe: <http://localhost:3000/supermercados> — returns the grouped payload,
  an empty payload with `"error": "Database connection error"` if Mongo is
  unreachable, or one with `"error": "Internal server error"` for a
  non-database defect (`api/blueprints/products.py`).
- Scraper control: <http://localhost:3000/api/scrapers> — one status snapshot
  per registered scraper (see §5).

## 4. Frontend

The global CLI is 14.x and cannot build an Angular 21 workspace. Use the local
one:

```bash
cd adminpro
npm install
npx ng serve            # → http://localhost:4200
npx ng build            # → writes into ../static
```

📖 INFERRED. `package.json` also exposes `npm start` (`ng serve --o`) and
`npm run build` (`ng build`), which resolve to the local CLI correctly once
`node_modules` exists.

**Dev-server caveat:** `adminpro/src/app/service/app.service.ts:21` hardcodes
`http://127.0.0.1:3000/supermercados`. There is no `environments/` directory, so
the API base URL is not configurable. `ng serve` on :4200 therefore depends on
the Flask backend running on :3000, and relies on the blanket `CORS(app)`.

### Build consequences — read before running `ng build`

- `angular.json:16-19` sets `outputPath: { "base": "../static", "browser": "" }`,
  so the build writes **directly into `static/`**, which is gitignored. A build
  therefore produces no git diff at all — only source changes do.
- Content-hashed filenames (`main-<hash>.js`) are replaced on every build, so
  stale bundles cannot accumulate in version control any more. They can still
  accumulate on disk if you build into a copy; the builder cleans its own
  `outputPath`, so a normal build is self-cleaning.

## 5. Running a scraper

Every supermarket is ported to the scraper contract and runs through the same
control API and registry (slugs: `supermami`, `laanonima`, `disco`,
`carrefour`, `changomas`):

```bash
curl -X POST http://localhost:3000/api/scrapers/disco/start?category=almacen   # 202, run starts in a worker thread
curl http://localhost:3000/api/scrapers/disco                                  # run status
curl -X POST http://localhost:3000/api/scrapers/disco/stop                     # cooperative stop
```

A second `start` while a run is active is a clean **409 `already_running`**; an
unknown slug is **404**, an unsupported category **400 `invalid_category`** with
the allowed list (ChangoMas accepts no category — any value is ignored;
SuperMami accepts `almacen`). The deprecated `POST /scraping-<slug>` /
`GET|POST /scraping-<slug>-stop` aliases do the same and return
`{"success": true}`.

Watch progress at <http://localhost:3000/scrape>: the admin page renders one
card per registered scraper, reads its state from `GET /api/scrapers` on load
and once per second, and starts/stops runs through the same API. It loads no
third-party asset and needs no realtime client. The Socket.IO channels
(`scraping-message-<slug>` and the aggregated `scraper-status`) are still
emitted by `api/sockets.py`, but no page subscribes to them any more: removing
them is an open decision, not a cleanup someone should do silently.

Before any of this works:

1. A browser run needs Chrome; Selenium Manager resolves the matching driver
   (network required on first use), or set `CHROMEDRIVER_PATH`. SuperMami, La
   Anónima, Carrefour and Disco never open a browser.
2. A visible browser window opens by default (`CHROME_HEADLESS` opts out). Do
   not run browser scrapers on a headless CI box expecting success — Chrome is
   not installed in the workflow.
3. **Every save REPLACES the scraper's slice** through
   `ProductRepository.replace_products` (insert first, then prune; an empty
   scrape is a no-op) — it does not append. Do not point a run at production
   data casually.
4. Disco reads the VTEX catalog API (like Carrefour) and its search endpoint
   rejects any offset window beyond item **2550** — oversized categories are
   split by price (`fq=P:[lo TO hi]`), so do not flatten the crawl or bump
   `MAX_WINDOW` (`api/scrapers/disco.py`).
5. Known per-scraper quirks kept verbatim by the ports: ChangoMás re-fetches
   the discovery page in its page loop, aborts the whole run on an empty first
   result, and is persisted but **not shown by `/supermercados`** (K-12). See
   [`known-issues.md`](known-issues.md) before treating any of them as a bug to
   fix silently. SuperMami (Oracle Endeca) pages the **parent** category flat
   with `No=`/`Nrpp=500` — the parent is the scope on purpose, because its
   level-2 children do not partition it (`almacen`: children sum 2 680 vs the
   parent's 3 210), so don't "fix" it into a children walk.

### Run a scraper from the shell — `python -m api.cli`

The CLI runs the same `ScraperManager` the control API uses, without Flask,
gunicorn or SocketIO (progress prints to stdout):

```bash
.venv/bin/python -m api.cli list                    # one line per registered scraper
.venv/bin/python -m api.cli run disco               # run one scraper and wait
.venv/bin/python -m api.cli run carrefour --category almacen
```

✅ VERIFIED: `python -m api.cli list` prints the five slugs in registration
order (`supermami`, `laanonima`, `disco`, `carrefour`, `changomas`) with
their accepted categories.

Exit codes: `0` succeeded, `1` failed, `2` stopped (including Ctrl+C — the
CLI requests a cooperative stop before exiting), `3` scraper-control error
(unknown slug, invalid category or already running; printed as a clean
`error: …` line, no traceback).

The `/scrape` monitor page is generated from the same registry: one card
per registered scraper, no hand-written HTML per supermarket.

## 6. Deploy — four contradictory stories, none chosen

| Path | Files | Status |
| --- | --- | --- |
| Docker | `Dockerfile` | ⚠️ **entry point now exists**: `main.py` provides `main:app` and was verified under gunicorn. Still unverified end to end — the image itself has never been built here (daemon not running). The frontend bundle is produced by a `node:24-alpine` stage. |
| Heroku-style | `Procfile` → `web: python app.py` | ⚠️ runs the Werkzeug dev server with `debug=True`; uses whatever `PORT` the platform injects |
| Gunicorn (orphan) | `gunicorn_config.py` (`0.0.0.0:3000`, 2 workers) | ⛔ referenced by nothing |
| App Engine | `app.yaml` (`runtime: python315`) | ⛔ no entrypoint declared |
| Cloud Foundry | `manifest.yml` (128 MB, service `crud`) | ⛔ memory far below what Chrome needs; leftover |

Before any hosted deploy can work, pick one of the four stories and retire the
rest: the WSGI blockers K-1/K-2 are fixed (`create_app` wires sockets and Mongo
for every entry point, verified under gunicorn), and `main.py` gives the
Dockerfile the entry point it always pointed at. What remains unverified is the
image build itself.

## 7. CI

`.github/workflows/python-app.yml` runs on push/PR to `main`:

1. `pip install -r requirements-dev.txt`
2. `flake8 . --select=E9,F63,F7,F82` (real gate) then a `--exit-zero` style pass
3. `pytest`

✅ The suite is green: 291 passed, 9 skipped (the opt-in MongoDB integration
tests) on this checkout. The first green run on GitHub Actions was not observed
here (K-6).

## 8. Verification checklist

After any change, confirm with runtime evidence — the pytest suite covers
watched behavior, but live scraping and the SPA are verified manually.

| Goal | How to confirm |
| --- | --- |
| Backend boots | `python app.py` serves :3000; or `python -c "from main import app; print(len(list(app.url_map.iter_rules())))"` → `19` |
| API alive | `curl -s localhost:3000/supermercados \| head -c 200` returns JSON with `todos` |
| Data present | `mongo`/Atlas: `use lalistitadev; db.productos.countDocuments()` |
| Scraper progressed | `/scrape` receives `scraping-message-<slug>` events; `GET /api/scrapers/<slug>` reports the state |
| Frontend renders | `npx ng build` first, then `GET /` → 200; without a build it must answer **503** with the build command |
| Bundle is not versioned | `git ls-files static/` → empty, and `git status` stays clean after a build |

### UI verification protocol — one hypothesis, one round

A browser is the only signal the SPA has, and the most expensive evidence this
repo can produce. Six rules keep it affordable (summary in
[`AGENTS.md`](../../AGENTS.md) §8):

1. **Static reading first.** Before any browser: the component
   (`adminpro/src/app/pages/dashboard/dashboard.component.ts`), the renderer
   (`cellRender.ts`), the template, the service, and the payload itself
   (`curl -s localhost:3000/api/...`). The hypothesis comes from those reads.
2. **State it as a falsifiable observable**, e.g. "clicking row 1's checkbox
   puts one product in each of the four small grids (4 rows total)", plus the
   one selector that proves or kills it.
3. **One round = one browser open**, every assertion batched: console errors,
   the target selector's state, and one count per affected list. Reuse the same
   page between rounds; do not restart the browser per check.
4. **No exploratory loops.** A round that neither confirms nor kills the
   hypothesis sends you back to static reading — never into a second
   exploratory round.
5. **Bounded output.** Counts, booleans, short text. No full DOM dumps, and no
   screenshots when a selector count answers the question.
6. **Record the round** — hypothesis, observation, conclusion — in the feature
   document under `odd/tasks/`.

Prerequisites: backend on :3000 with the real database, a built bundle (`ng
build`) or `ng serve`, and the real route (`/#/dashboard`). A UI that renders
layout with no data before touching anything is trap **T-11** in `AGENTS.md`,
not a data problem.

---

## Security note — why this file avoids exact version numbers

This repository is **public**. Earlier revisions of this file recorded the exact
patch versions of the local toolchain (browser build, interpreter, Node, npm,
CLI) and an absolute framework path. That is a machine fingerprint: a specific
browser build tells an attacker which patches are missing, and an absolute path
discloses the install layout.

Rules for future edits:

- Write `3.15.x`, `156.x`, `Node 26.x` — never the full build string.
- Never commit `/Users/<name>/...` or an absolute framework path.
- Never commit a personal email address. `git config user.email` is global on
  this machine; check it before committing.
- Credentials scan before any commit that touches config:
  `git grep -nIE "mongodb\+srv://[^\"' ]*:[^\"' @]+@"`

Exact versions belong in the commit message of the change that depends on them,
or in the private task document — not in a published file.
