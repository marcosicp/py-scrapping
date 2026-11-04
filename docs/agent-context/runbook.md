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

Environment measured on macOS, Python 3.15.x, Node 26.x, npm 11.x,
Chrome 156.x. Exact patch versions are deliberately omitted — see the security
note at the end of this file.

---

## 0. Prerequisites — the state of this checkout

| Item | Measured | Verdict |
| --- | --- | --- |
| `.venv` | Python 3.15.x, provisioned, 53 packages | ✅ working |
| Python target | 3.15.2 pinned in `.python-version`, `runtime.txt`, `Dockerfile`, `app.yaml`, CI | ✅ aligned |
| `static/` bundle | **absent in a fresh clone** — gitignored build output | ⛔ `npm ci && npm run build` |
| `python3` on PATH | still resolves to an older framework build because PATH order wins over `/usr/local/bin` | ⚠️ call `python3.15` explicitly |
| `adminpro/node_modules` | absent | ⛔ `npm install` required |
| Global `ng` | Angular CLI 14.x, `Node ... (Unsupported)` | ⛔ too old for Angular 21 — use the local CLI |
| ChromeDriver | pinned to Chrome 141 | ⚠️ `/usr/local/bin/chromedriver-141` |
| Chrome | 156.x | ⛔ mismatch with the pinned driver → every scraper fails |
| `.env` | absent (gitignored) | ⛔ `MONGODB_URI` must be provided |
| Tests | none (`pytest` not even installed) | — |

## 1. Backend: the virtualenv

Already provisioned. Recreate it only if it is missing or broken:

```bash
rm -rf .venv
python3.15 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

✅ VERIFIED on Python 3.15.2 — installs with no source builds, 53 packages,
and `uvx pip-audit --path .venv/lib/python3.15/site-packages` reports
**no known vulnerabilities**.

Notes that will save you time:

- **`requirements.txt` pins direct dependencies only.** Transitive packages float
  on purpose so security patches arrive without a manual bump. The file used to
  be a full `pip freeze` and accumulated 91 advisories doing exactly that.
- **`lxml_html_clean` is mandatory.** `lxml` 5.2 moved `lxml.html.clean` into its
  own project and `requests-html` imports it unconditionally. Without it,
  `import requests_html` fails and therefore the whole app fails to import.
- **Do not add a bare `bson` requirement** — the standalone PyPI package shadows
  pymongo's bundled `bson` and breaks the driver.
- `requests-html` is abandoned (2019) and its rendering path is broken; see
  known-issues K-18 before assuming any scraper works.

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

✅ VERIFIED: `pytest` collects the suite in `tests/` and exits 0. No test touches
the network, Chrome or a real database — the Mongo fixtures point at an
unroutable URI (`mongodb://127.0.0.1:1/…`), so an accidental connection fails
fast instead of reaching any server. The `flake8` gate used by CI is
`flake8 . --exclude .venv,adminpro,static,node_modules --select=E9,F63,F7,F82 --count`.
Settings (`SECRET_KEY`, `MONGODB_URI`, `MONGODB_DB`) are resolved in
`api/config.py` (`Settings.from_env`); `app.py` consumes them via
`create_app(settings)`.

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
| `CHROMEDRIVER_PATH` | unset → Selenium Manager picks a matching driver (needs network on first use) | read by `Settings.from_env`; honored by scrapers that run through `ctx.browser()` (the ported ones) — the not-yet-ported legacy scrapers still use their hardcoded driver path (K-7) |
| `CHROME_HEADLESS` | off | opt-in headless: `1`, `true`, `yes`, `on` (case-insensitive, surrounding whitespace ignored) add `--headless=new`; same ported/legacy caveat as `CHROMEDRIVER_PATH` |

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
  or an empty payload with `"error": "Database connection error"` if Mongo is
  unreachable (`api/routes.py:137`).
- `/supermercado-<chain>` routes answer **500** by design-of-bug: they read JSON
  files that do not exist (K-11).

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

```bash
curl -X POST "http://localhost:3000/scraping-carrefour?category=almacen"
curl -X POST "http://localhost:3000/scraping-disco?category=almacen"      # ⛔ broken route, see known-issues K-5
curl    "http://localhost:3000/scraping-changomas-stop"                   # ⛔ returns 500
```

Watch progress at <http://localhost:3000/scrape> (SocketIO channels
`scraping-message-<supermarket>`).

Before any of this works:

1. Chrome and ChromeDriver must match. Four of the five scrapers hardcode
   `/usr/local/bin/chromedriver-141` while Chrome is 156 → "session not created".
   Fix by installing the driver matching the installed Chrome and either
   symlinking it to that path or editing the four scrapers. (The ported
   SuperMami needs no driver at all — it scrapes plain HTTP responses.)
2. `?category=` only matches `"almacen"`; any other value is silently ignored.
3. A visible browser window opens (only HiperLibertad is headless). Do not run
   scrapers on a headless CI box expecting success — Chrome is not installed in
   the workflow.
4. **Carrefour deletes before inserting** (`scrap_carrefour.py:43`): running it
   against a real database removes that category's existing rows first.

### Run one supermarket scraper (ported scrapers only)

SuperMami (`api/scrapers/supermami.py`) is the first scraper ported to the
new contract, so it also runs through the modern control API (no Chrome, no
hardcoded driver):

```bash
curl -X POST http://localhost:3000/api/scrapers/supermami/start        # 202, run starts
curl http://localhost:3000/api/scrapers/supermami                     # run status
curl -X POST http://localhost:3000/api/scrapers/supermami/stop        # cooperative stop
```

A `start` returns **202** immediately while the run happens in a background
thread, and progress arrives over Socket.IO (channel
`scraping-message-supermami`); watch it at <http://localhost:3000/scrape>.
SuperMami needs no browser and no `?category=` (its category list is empty,
any value is ignored).

## 6. Deploy — three contradictory stories, all currently broken

| Path | Files | Status |
| --- | --- | --- |
| Docker | `Dockerfile` | ⚠️ **entry point now exists**: `main.py` provides `main:app` and was verified under gunicorn. Still unverified end to end — the image itself has never been built here (daemon not running). The frontend bundle is produced by a `node:24-alpine` stage. |
| Heroku-style | `Procfile` → `web: python app.py` | ⚠️ runs the Werkzeug dev server with `debug=True`; uses whatever `PORT` the platform injects |
| Gunicorn (orphan) | `gunicorn_config.py` (`0.0.0.0:3000`, 2 workers) | ⛔ referenced by nothing |
| App Engine | `app.yaml` (`runtime: python310`) | ⛔ no entrypoint declared |
| Cloud Foundry | `manifest.yml` (128 MB, service `crud`) | ⛔ memory far below what Chrome needs; leftover |

Before any hosted deploy can work, the WSGI blockers in
[`known-issues.md`](known-issues.md) K-1 and K-2 must be fixed: under gunicorn,
SocketIO is never initialized and `current_app.mongodb_client` does not exist.

## 7. CI

`.github/workflows/python-app.yml` runs on push/PR to `main`:

1. `pip install flake8 pytest` + `requirements.txt`
2. `flake8 . --select=E9,F63,F7,F82` (real gate) then a `--exit-zero` style pass
3. `pytest`

⛔ **Step 3 fails on every run**: the repository has zero test files, and pytest
exits 5 ("no tests collected"), which the job treats as failure. Verified by
`git ls-files | grep -cE '(_test|test_).*\.py'` → `0`.

## 8. Verification checklist

After any change, confirm with runtime evidence — there is no test suite to lean
on.

| Goal | How to confirm |
| --- | --- |
| Backend boots | `python app.py` logs `Connected to the MongoDB database!` (`app.py:34`) |
| API alive | `curl -s localhost:3000/supermercados \| head -c 200` returns JSON with `todos` |
| Data present | `mongo`/Atlas: `use lalistitadev; db.productos.countDocuments()` |
| Scraper progressed | log lines + `/scrape` receives `scraping-message-<x>` events |
| Frontend renders | `npx ng build` first, then `GET /` → 200; without a build it must answer **503** with the build command |
| Bundle is not versioned | `git ls-files static/` → empty, and `git status` stays clean after a build |

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
