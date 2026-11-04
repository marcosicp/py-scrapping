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

Environment measured on macOS, Python 3.11.1, Node 26.7.0, npm 11.19.0,
Chrome 156.0.8078.80.

---

## 0. Prerequisites — the state of this checkout

| Item | Measured | Verdict |
| --- | --- | --- |
| `.venv` | exists, `pyvenv.cfg` → `/Library/Frameworks/Python.framework/Versions/3.11`, but `.venv/bin/pip` fails with `bad interpreter: No such file or directory` | ⛔ broken, recreate |
| Global `python3` | 3.11.1; has flask 3.1.2, flask-socketio, pymongo, selenium, requests_html, bs4, dotenv, lxml — **missing `flask_cors`** | ⛔ `python3 app.py` dies at `app.py:5` |
| `adminpro/node_modules` | absent | ⛔ `npm install` required |
| Global `ng` | **Angular CLI 14.2.10**, `Node: 26.7.0 (Unsupported)` | ⛔ too old for Angular 19 — use the local CLI |
| ChromeDriver | `/usr/local/bin/chromedriver-141` exists | ⚠️ pinned to Chrome 141 |
| Chrome | **156.0.8078.80** | ⛔ mismatch with the pinned driver → every scraper fails |
| `.env` | absent (gitignored) | ⛔ `MONGODB_URI` must be provided |
| Tests | none (`pytest` not even installed) | — |

## 1. Backend: recreate the virtualenv

```bash
python3 -m venv .venv                 # overwrites the broken one; safe
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

📖 INFERRED — not executed during bootstrap (network install).

Known friction in `requirements.txt`:

- `requests-html==0.10.0` pulls `pyppeteer`, which downloads its own Chromium on
  first `arender()` call (Disco and Carrefour use it). A second browser
  dependency, separate from ChromeDriver.
- `bs4==0.0.1` is a meta-package whose only job is to require
  `beautifulsoup4` — already pinned here. Redundant but harmless.
- Pins are hard (`==`), so on Python 3.11 expect at least one dependency to need
  a bump. If install fails, the target interpreter is **3.10** per
  `Dockerfile:4` and the CI workflow.

To fall back to the global interpreter instead of a venv, the only missing
module is `flask_cors`:

```bash
pip install flask-cors==4.0.0     # 📖 INFERRED, does not pin the rest
```

## 2. Environment variables

Create `.env` at the repo root (gitignored, never commit):

```env
MONGODB_URI=mongodb+srv://<user>:<password>@<cluster>/<db>?retryWrites=true&w=majority
PORT=3000
```

- `MONGODB_URI` is read at `app.py:31` and `app.py:40`; without it the dev branch
  falls back to `mongodb://localhost:27017/`.
- `PORT` (`cf_port`) only switches which `app.run` branch executes; both call
  `debug=True`.
- The database actually queried is hardcoded to **`lalistitadev`**
  (`api/routes.py:94`) — the URI's own database segment is ignored. Collection:
  `productos`.

## 3. Run the backend

```bash
source .venv/bin/activate
python app.py
```

📖 INFERRED. Expects a reachable MongoDB.

- App: <http://localhost:3000> — serves `static/index.html` (the committed
  Angular bundle), **not** `adminpro/src`.
- Scraper monitor: <http://localhost:3000/scrape>
- API probe: <http://localhost:3000/supermercados> — returns the grouped payload,
  or an empty payload with `"error": "Database connection error"` if Mongo is
  unreachable (`api/routes.py:137`).

## 4. Frontend

The global CLI is 14.x and cannot build an Angular 19 workspace. Use the local
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
  so the build writes **directly into the committed `static/`** directory.
- Filenames are content-hashed (`main-KNNEIXUN.js`). A rebuild leaves the previous
  hashes behind as orphans: the working tree gains new files and keeps stale ones.
- `static/index.html` is overwritten by every build.
- Never mix a build into a commit that is about something else.

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
   symlinking it to that path or editing the four scrapers (SuperMami has no
   driver — it relies on `requests_html`'s own bundled Chromium).
2. `?category=` only matches `"almacen"`; any other value is silently ignored.
3. A visible browser window opens (only HiperLibertad is headless). Do not run
   scrapers on a headless CI box expecting success — Chrome is not installed in
   the workflow.
4. **Carrefour deletes before inserting** (`scrap_carrefour.py:43`): running it
   against a real database removes that category's existing rows first.

## 6. Deploy — three contradictory stories, all currently broken

| Path | Files | Status |
| --- | --- | --- |
| Docker | `Dockerfile` | ⛔ `CMD ... main:app` (`Dockerfile:22`) but there is **no `main.py`**. The image builds, the container crashes at start. |
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
| Frontend renders | `npx ng serve`, open :4200, grid shows rows (or empty grid when the API is down) |
| Build matches source | `git status static/` shows the expected new hashes only |
