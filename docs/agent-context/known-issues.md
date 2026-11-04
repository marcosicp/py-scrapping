# Known issues

Defect register for LaListita. Every entry was found by reading the code during
the agent-context bootstrap on `main@06b37b7` and is cited with `path:line`.
Statuses were reconciled with the backend after T1-T14a of
`odd/tasks/backend-architecture.md` (branch `feat/backend-architecture@30b20cb`).

Each entry is written to be liftable into its own ODD task / work-unit commit.
When you fix one, change its status to `fixed`, add the commit sha, and leave
the entry in place — the history is the point. Citations that point at code
deleted since the bootstrap are marked *(code gone)*; citations to live code
were re-verified line by line.

Entry point for agents: [`AGENTS.md`](../../AGENTS.md).

---

## Summary

| ID | Severity | Area | Status |
| --- | --- | --- | --- |
| [K-1](#k-1) | Critical | Runtime | **fixed** — SocketIO initialized by the factory |
| [K-2](#k-2) | Critical | Runtime | **fixed** — Mongo handles attached by the factory |
| [K-3](#k-3) | High | Data | **fixed** — database name centralized on `lalistitadev` |
| [K-4](#k-4) | High | API | **fixed** — route deleted with the legacy layer (`4665c1c`) |
| [K-5](#k-5) | High | Deploy | **fixed** — `main.py` exists, verified under gunicorn |
| [K-6](#k-6) | High | Deploy | **fixed** — pytest suite in `tests/`, CI installs dev deps (sha pending) |
| [K-7](#k-7) | High | Scrapers | **fixed** — one Chrome factory, Selenium Manager default (`a4bbd18` + ports) |
| [K-8](#k-8) | High | Data | **fixed** — repository inserts before pruning (`6790b1e`) |
| [K-9](#k-9) | Medium | API | **fixed** — all runs go through `ScraperManager` threads (`7ff8ff2` + ports) |
| [K-10](#k-10) | Medium | API | **fixed** — stop returns 202 with a status snapshot (`7ff8ff2`) |
| [K-11](#k-11) | Medium | API | **fixed** — dead `/supermercado-*` routes deleted (`30b20cb`) |
| [K-12](#k-12) | Medium | Data | **partially fixed** — ChangoMás persists (`9d9248d`); `/supermercados` + dashboard still ignore the group |
| [K-13](#k-13) | Medium | Security | open — unauthenticated scraper control + wide-open CORS |
| [K-14](#k-14) | Medium | Tooling | **fixed** — venv provisioned on Python 3.15.x |
| [K-15](#k-15) | Medium | Tooling | open — global Angular CLI too old |
| [K-16](#k-16) | Low | Hygiene | **partially fixed** — legacy layer deleted (`30b20cb`); dead templates and `api/models/productos.py` remain |
| [K-17](#k-17) | Low | Perf | open — full-collection scan on every API call |
| [K-18](#k-18) | High | Scrapers | **fixed** — `arender()` never ran (missing `await`); dependency removed with the ports |

---

## <a id="k-1"></a>K-1 · SocketIO is never initialized outside `python app.py`

**Status: fixed.** `configure_sockets(app)` is now called by `create_app()`, which
runs for every entry point. `main.py` gives WSGI servers a module-level `app`.

Verified under real gunicorn (`gunicorn --bind 127.0.0.1:8124 main:app`): the
Engine.IO handshake answers with a valid session —
`GET /socket.io/?EIO=4&transport=polling` → `0{"sid":"…","upgrades":["websocket"]…}`.
Before the fix that path had no initialized server behind it.

Original symptom, retained for searchability:

`configure_sockets(app)` was called at `app.py:26`, inside
`if __name__ == '__main__':`. Any WSGI server (gunicorn, uWSGI, Cloud Run,
Heroku, App Engine) imports `app` as a module, so `__main__` never runs and
`socketio.init_app(app)` never happens.

**Impact:** every `notifyStatus()` call emitted on an uninitialized SocketIO
object (today the emit lives in `SocketIOReporter`, `api/sockets.py:28,31`);
`/scrape` showed nothing. Failure was silent — no exception surfaced to the user.

Related: `async_mode` is `threading` because neither `eventlet` nor `gevent` is
installed, so realtime works over long-polling but not the WebSocket transport.

## <a id="k-2"></a>K-2 · `current_app.mongodb_client` does not exist under WSGI

**Status: fixed.** `_init_mongo(app)` now runs inside `create_app()` and always
creates the client — previously it was created only when `MONGODB_URI` happened to
be set, in the `__main__` branch.

Verified: inside `app.app_context()`, `current_app.mongodb_client` resolves to a
`MongoClient` and `current_app.database.name == "lalistitadev"`. Under gunicorn,
`GET /` returns 200 with 71993 bytes and `GET /scrape` returns 200 — neither raised
`AttributeError`.

Original symptom, retained for searchability:

The client was attached at `app.py:32` and `app.py:42`, both inside the
`__main__` block, while consumers read `current_app.mongodb_client`: the
`/supermercados` handler and three of the legacy scrapers
(`scrap_carrefour.py:38`, `scrap_hiperlibertad.py:32`, `scrap_supermami.py:101`
— code gone).

**Impact:** under gunicorn these raised `AttributeError`. `/supermercados` caught
it in its `except` (`api/blueprints/products.py`) and returned an empty payload,
so the breakage looked like "no data" rather than "misconfigured app".
Today no consumer reads `current_app.mongodb_client` directly: persistence goes
through the `ProductRepository` (`api/repositories/products.py`), which the
composition root builds from the client.

## <a id="k-3"></a>K-3 · Two database names; the one that is set is dead

**Status: fixed.** `_init_mongo` now sets `app.database` from `MONGODB_DB` with the
default **`lalistitadev`**, the database every consumer already used. The dead
`"lalistita"` is gone. Verified: `app.database.name == "lalistitadev"`.

Original symptom, retained for searchability:

The `__main__`-only wiring set `app.database = client["lalistita"]` (code gone)
while every consumer used `client.lalistitadev` (the repository and, then, the
legacy scrapers).
`app.database` was never read, so the value was pure misinformation.

## <a id="k-4"></a>K-4 · `/scraping-disco` calls the scraper inline and then crashes

**Status: fixed** (`4665c1c`). The Disco route was deleted with the legacy
scraper layer (`api/routes.py` no longer exists — code gone). Disco is now
`ScraperDisco` (`api/scrapers/disco.py`), started through
`POST /api/scrapers/disco/start` (202) or the registry-generated alias
`POST /scraping-disco`, both backed by the `ScraperManager` worker thread.

Original symptom, retained for searchability:

```python
Thread(target = scrape_service.scrape_disco(categoria),).start()   # api/routes.py:34
```

`scrape_disco(categoria)` is **called**, not referenced. The whole scrape runs
synchronously inside the HTTP request, returns `None`, and then
`Thread(target=None).start()` raises `TypeError`. Compare the correct form two
routes down (`api/routes.py:62`).

**Impact:** the request blocks for the entire Disco scrape (many minutes, five
paginated subcategories) and then returns 500. Disco had no working start route
at all.

**Fix (shipped):** the whole legacy route layer was replaced by the scraper
contract; see K-9.

## <a id="k-5"></a>K-5 · Docker image builds, then crashes on start

**Status: fixed.** `main.py` now exists and exposes the module-level `app` the
`CMD` already pointed at. Verified by running the exact command the image runs:

```
gunicorn --bind 127.0.0.1:8124 --workers 1 main:app
  GET /        -> 200, 71993 bytes
  GET /scrape  -> 200, 6524 bytes
  GET /socket.io/?EIO=4&transport=polling -> 200, valid sid
```

Not verified: `docker build` itself — the Docker daemon is not running on this
machine, so the image (including the multi-stage frontend build) is unbuilt code.

Still open in this area: **the repository has four deploy stories** (`Dockerfile`,
`Procfile`, `gunicorn_config.py`, `app.yaml`, `manifest.yml`). Only the Dockerfile
and `main.py` are coherent; picking one story is a separate decision.

Original symptom, retained for searchability:

`Dockerfile:22` → `CMD exec gunicorn ... main:app` with no `main.py` in the
repository. Nothing produced or imported `main`, so the image built and the
container died at boot. Combined with K-1/K-2, pointing it at `app:app` would
have deployed a service with dead realtime and no database.

## <a id="k-6"></a>K-6 · CI is red on every push because there are no tests

**Severity:** High (destroys the signal value of CI).

**Status: fixed — verified locally (pytest exit 0, flake8 gate 0); first run on
GitHub Actions not yet observed.** (commit sha pending)

The install step now reads `requirements-dev.txt` (`requirements.txt` plus
pinned pytest and flake8), and a pytest suite lives in `tests/` (settings and
app-factory tests, with fixtures in `tests/conftest.py`; the suite grows as the
backend-architecture work proceeds).

Original symptom, retained for searchability:

`.github/workflows/python-app.yml` ends with `pytest`. The repo had zero Python
test files and did not even list pytest in `requirements.txt` (the workflow
installed it ad hoc). Pytest exited **5 — no tests collected**, which the job
treats as failure.

**Impact:** a permanently red check trains everyone to ignore CI. The only real
gate was `flake8 --select=E9,F63,F7,F82` (syntax + undefined names); the second
flake8 invocation is `--exit-zero`.

## <a id="k-7"></a>K-7 · ChromeDriver pinned to 141, Chrome is 156

**Status: fixed** (`a4bbd18`, completed by the T7-T11 ports). Driver
construction is centralized in `api/scrapers/browser.py`: with
`CHROMEDRIVER_PATH` set, that binary is passed to `Service`
(`api/scrapers/browser.py:52-53`); unset (the default), `Service()` lets
Selenium Manager resolve a driver matching the installed Chrome
(`api/scrapers/browser.py:54-55`). No scraper hardcodes a driver path any more.

Original symptom, retained for searchability:

`Service('/usr/local/bin/chromedriver-141')` appeared in four of the five
scrapers (`scrap_disco.py:65`, `scrap_carrefour.py:75`, `scrap_changomas.py:35`,
`scrap_hiperlibertad.py:64` — code gone). **SuperMami had no driver** — it used
`requests_html` only, despite importing selenium modules it never calls.

**Impact (then):** every scraper failed with `session not created: This version
of ChromeDriver only supports Chrome version 141`.

## <a id="k-8"></a>K-8 · Carrefour replaces a whole category before scraping

**Status: fixed** (`6790b1e`). Persistence goes through
`ProductRepository.replace_products` (`api/repositories/products.py:42`):
an empty scrape is a no-op returning 0 (`api/repositories/products.py:65-66`),
the new documents are inserted **before** the old ids are pruned
(`api/repositories/products.py:90-98`), so a failed insert leaves the previous
data intact.

Original symptom, retained for searchability:

`api/scrapers/scrap_carrefour.py:43` (code gone):

```python
collection.delete_many({"supermercado": "Carrefour", "categoria": category_name})
```

then `insert_many` at `:52`.

**Impact:** if the scrape failed after the delete — a site change, a network
blip — the category was left empty in production. No transaction, no staging
collection, no backup.

**Residual risk:** if the insert fails after some batches were already written
(a chunked driver write), the slice can temporarily hold old + partial new
documents; the next successful replace converges it
(`api/repositories/products.py:55-59`).

## <a id="k-9"></a>K-9 · Two scraper routes block the worker

**Status: fixed** (`7ff8ff2`, completed by the ports). Every start goes through
`ScraperManager.start` (`api/services/scraping.py`), which runs the scraper in
a daemon worker thread and returns a `RunStatus` snapshot immediately; the HTTP
layer answers 202 (`api/blueprints/scrapers.py`). All five scrapers are ported,
so no request ever runs a scrape inline.

Original symptom, retained for searchability:

`/scraping-hiperlibertad` (`api/routes.py:38`) and `/scraping-supermami`
(`api/routes.py:46`) called the scraper inline; only `/scraping-carrefour` and
`/scraping-changomas` spawned a thread (code gone).

**Impact:** with gunicorn's default of 1–2 workers, two concurrent scrape
requests exhausted the pool and the whole app stopped answering until the
scrapes finished.

## <a id="k-10"></a>K-10 · Stop routes return `None`

**Status: fixed** (`7ff8ff2`). The stop endpoint is
`POST /api/scrapers/<slug>/stop` (`api/blueprints/scrapers.py`) and returns 202
with a `RunStatus` snapshot; a stop of an inactive scraper is a clean 409
`not_running`, and the registry-generated `/scraping-<slug>-stop` aliases
return `{"success": true}` (`api/blueprints/legacy.py`). No view falls off the
end without a response.

Original symptom, retained for searchability:

`/scraping-supermami-stop` (`api/routes.py:53`) and `/scraping-changomas-stop`
(`api/routes.py:84`) ended after the `scrape_*_stop()` call with no `return`
(code gone).

**Impact:** Flask raised `TypeError: The view function did not return a valid
response` → HTTP 500, even though the stop flag was set successfully. Callers
saw failure and could retry.

## <a id="k-11"></a>K-11 · Dead `/supermercado-*` routes read files that cannot exist

**Status: fixed** (`30b20cb`). `api/routes.py` was deleted with the legacy
layer; the four routes no longer exist (code gone).

Original symptom, retained for searchability:

`api/routes.py:150-184` defined four routes that `open('carrefour.json')`,
`'disco.json'`, `'hiperlibertad.json'`, `'supermami.json'` — none of which
existed in the repo (`*.json` is gitignored at `.gitignore:56`), and afterwards
ignored the parsed data entirely by returning `static/index.html`.

**Impact:** any hit was a 500; readers assumed per-supermarket pages exist.

## <a id="k-12"></a>K-12 · ChangoMás writes only to local JSON files

**Status: partially fixed** (`9d9248d`). The scraper is ported
(`api/scrapers/changomas.py`) and persists through `ctx.save` →
`ProductRepository.replace_products` instead of dumping
`.changomas/almacen/<file>.json` (code gone).

**Still open (API half):** `/supermercados` has no `changomas` branch — the
grouping in `api/services/products.py:36-43` matches only `disco`, `carrefour`,
`hiper*` and `mami*`, so ChangoMás products never appear in the payload or in
the dashboard counts.

Original symptom, retained for searchability:

`api/scrapers/scrap_changomas.py:147` dumped to `.changomas/almacen/<file>.json`
and never called a `save_to_mongodb`; `/supermercados` had no `changomas`
branch.

**Impact:** ChangoMás appeared in the README, the UI and the route table but its
data was never queryable. `.changomas/` is gitignored, so the data was also
ephemeral.

**Remaining fix direction:** add a `changomas` group + count in
`api/services/products.py` and the dashboard, then update the README table.

## <a id="k-13"></a>K-13 · Anyone can start a scrape; CORS is wide open

**Severity:** Medium.

`app.py:74` → `CORS(app)` with no origins restriction. The scraper-control API
and its `/scraping-<slug>` aliases (`api/blueprints/scrapers.py`,
`api/blueprints/legacy.py`) are unauthenticated and `POST`/`GET` from any
origin. `SECRET_KEY = 'secret!'` is the fallback (`api/config.py`, consumed at
`app.py:76`).

**Impact:** a third-party page can trigger scrapes against the operator's IP and
mutate MongoDB (K-8 makes one of them destructive). Also an open relay for
resource abuse.

**Fix direction:** restrict `CORS` to known origins and put the scraper-control
routes behind a token (`Authorization: Bearer $ADMIN_TOKEN`). Read `SECRET_KEY`
from the environment.

## <a id="k-14"></a>K-14 · `.venv` is broken and blocks every Python command

**Status: fixed.** The venv was rebuilt from the Python 3.15.2 interpreter. The
entry is kept because the failure mode is worth knowing: the old venv's
`pyvenv.cfg` pointed at a framework interpreter that no longer existed, so every
`pip` and `python` call inside it died with `bad interpreter`.

**Lesson:** a venv is not portable across interpreter reinstalls. If Python is
upgraded or removed, `rm -rf .venv` and recreate — do not debug the symlink.

Original symptom, retained for searchability:

**Severity:** Medium (first-run blocker).

`pyvenv.cfg` recorded a `home` pointing at a Python 3.11 framework install that
no longer existed on disk, so the interpreter inside the venv failed:
`.venv/bin/pip: … bad interpreter: No such file or directory`.

**Impact:** `source .venv/bin/activate && pip …` and `python app.py` both fail.
An agent that assumes the venv is usable burns turns on a broken symlink.

**Fix direction:** this is a local-state issue, not a repo defect — but it should
be asserted. `.venv/` is already gitignored, so the reproducible path is: delete,
`python3 -m venv .venv`, `pip install -r requirements.txt`. Optionally document
the interpreter in a `.python-version`.

## <a id="k-15"></a>K-15 · The global Angular CLI cannot build this workspace

**Severity:** Medium (first-run blocker).

`ng version` → `Angular CLI 14.x`, `Node 26.x (Unsupported)`. The workspace
is Angular **21.2.x** with the `application` builder
(`@angular-devkit/build-angular:application`), which CLI 14 does not have.

**Impact:** `ng build` / `ng serve` from the global CLI fail with builder
resolution errors. `package.json` scripts are fine *after* `npm install`, because
they resolve `node_modules/.bin/ng`.

**Fix direction:** document `npx ng` / `node_modules/.bin/ng` as the only
supported invocation, and pin Node via `.nvmrc` / `engines` (`package.json` has
neither). Node 26 is untested by Angular 21 — the CLI accepts it (`>=24`) but
warns.

## <a id="k-16"></a>K-16 · Dead modules, duplicated build output, repeated imports

**Status: partially fixed** (`30b20cb`). The legacy scraper layer — including
the duplicated `from threading import Thread` imports and the never-used
`redirect_url()` of `api/routes.py` — is deleted (code gone).

**Still present:**

- `api/models/productos.py` — `from pymongo import pymongo` then
  `pymongo.Document` / `pymongo.StringField`. Those are mongoengine APIs; the
  module cannot work. Imported by nothing.
- `templates/index.html`, `index3.html`, `index4.html`, `indexa.html` — Angular
  build output committed as Jinja templates (`data-critters-container`). No route
  renders them.
- `templates/index2.html` — legacy server-rendered page, never rendered.
- `gunicorn_config.py`, `app.yaml`, `manifest.yml` — orphaned deploy configs (see
  K-5).

**Remaining fix direction:** delete.

Separately decided and shipped: `static/` is no longer versioned. It was 662
files / 17 MB, and a single Angular rebuild produced a 3.8 MB diff of minified
bundles — enough to make native review reject the candidate outright with
`lens_context_budget_exceeded` (97.7% of the candidate was build output). It is
now gitignored, built with `npm ci && npm run build`, produced inside the Docker
image by a `node` stage, and `/` answers 503 with the command when the bundle is
missing.

## <a id="k-17"></a>K-17 · Every API call scans the whole collection

**Severity:** Low now, scales badly.

`api/repositories/products.py:38-40` `find_all` →
`list(collection.find({}, {"_id": 0}))` (legacy: `api/routes.py:98`, code
gone), then Python-side grouping in `api/services/products.py`, O(n²)-ish dedupe
(`api/helpers.py:3-8` loop with `not in`), and a sort. No indexes are created
anywhere.

**Impact:** `/supermercados` loads every product of every supermarket into memory
per request and runs dedupe in Python. Fine for a few thousand rows, not for a
full catalog.

**Fix direction:** aggregate in Mongo (`$group` / `$match` on `supermercado`), add
a compound index on `(supermercado, name)`, and paginate.

## <a id="k-18"></a>K-18 · `arender()` never executed: a coroutine nobody awaited

**Status: fixed.** `requests-html`, `lxml_html_clean` and `webdriver-manager`
are gone from `requirements.txt`, and every scraper port (T7-T11, dependency
removal completed in `30b20cb`) deleted the `arender()` calls.

**Corrected diagnosis.** The bootstrap analysis below identified a real
breakage but blamed the wrong trigger. `requests_html`'s `arender()` is an
`async def` coroutine: calling it only creates the coroutine object. Every call
site — Disco, Carrefour, ChangoMás, SuperMami — wrote `session.arender(sleep=N)`
with **no `await`** and never ran the event loop, so **the render never
executed at all**, on any Python version. The scrapers worked (when they
worked) on the plain HTML response alone; the pyppeteer/Chromium path below was
never reached. The pyppeteer breakage was real but latent — it is what *would*
have happened had a call site ever awaited.

Original analysis, retained for searchability (wrong on the key point: the
calls never ran):

`requests-html 0.10.0` (last release 2019) declares `pyppeteer>=0.0.14` with no
upper bound, and the resolver settles on `pyppeteer 0.0.25`. That version calls:

```python
# pyppeteer/connection.py:43-44
self._ws = websockets.client.connect(
    self._url, max_size=None, loop=self._loop)
```

Verified on the rebuilt Python 3.15.x venv, `pyppeteer 0.0.25` fails three
independent ways before any page is fetched:

1. `websockets.client` **no longer exists** — the submodule was removed. In the
   installed `websockets 17.4`, `hasattr(websockets, "client")` is `False`, so
   line 43 raises `AttributeError` outright.
2. `websockets.ConnectionClosed` (used at lines 62 and 74) was also relocated.
3. Even if both existed, `loop=` is forwarded to `create_connection`, which
   stopped accepting it in Python 3.10.

`websockets` deprecated `loop` in 10.0 and later versions forward unknown keyword
arguments down to `asyncio.BaseEventLoop.create_connection`, which **stopped
accepting `loop` in Python 3.10**. Measured behaviour on this machine:

| `websockets` | `connect(loop=...)` | Result |
| --- | --- | --- |
| 10.4 | consumed by websockets | works |
| 12.0 (the repo's old pin) | forwarded to asyncio | fails on Python ≥3.10 |
| 17.4 (current) | `websockets.client` gone | `AttributeError` before the call |

**Impact (then):** had any call site awaited, `arender()` would have raised
before fetching a page, breaking Disco, Carrefour, ChangoMás and SuperMami.
HiperLibertad was unaffected (pure VTEX JSON API). This was **pre-existing**:
the old pins (`websockets==12.0`, Python 3.11) were already broken for the same
reason.

**Why a pin fix would not have worked:** keeping `arender()` alive requires
`pyppeteer==2.0.0` (which pins `websockets==10.4`), and that in turn pins
`urllib3==1.26.20` — measured at **12 advisories** (`PYSEC-2026-141`,
`-1994`…`-1999`, `-4175`, `-4177`). Trading 12 CVEs for a broken helper is not a
fix.

**Fix (shipped):** stop using `arender()`. The ports render through the
Selenium driver behind `ctx.browser()` where rendering is needed (Disco,
Carrefour, ChangoMás) or parse the plain HTTP response directly (HiperLibertad,
SuperMami) — no second browser, no abandoned dependency.

**Disposition (`scrape-admin-view` T1):** the HiperLibertad scraper no longer
exists. `hiperlibertad.com.ar` now answers **301** to `laanonima.com.ar` and the
VTEX search API it consumed answers **403**; it was replaced by
`api/scrapers/laanonima.py`, which reads the site's JSON-LD `ItemList` and
stores under `supermercado = "La Anónima"`. `/supermercados` keeps serving it
through the `hiper` payload key the dashboard already renders.

---

## Minor observations (not filed)

- `name_parse`'s regex includes bare `m` as a unit (`api/helpers.py:17`), so a
  name containing "100 m" can be mis-parsed. It also strips only the first match.
- Duplicate suppression is substring-based, still live in the ported scrapers
  (e.g. `api/scrapers/disco.py:149-152`, `api/scrapers/carrefour.py:178`), which
  drops legitimately distinct products whose names contain another product's name.
- Driver cleanup is now uniform: `ctx.browser()` quits the driver in a `finally`
  (`api/scrapers/base.py`), so the old "only ChangoMás closes its driver" leak is
  gone.
- `scraped_at` is stamped with `datetime.now(timezone.utc)` at save time
  (`api/repositories/products.py:77`) — the deprecated `datetime.utcnow()` is
  gone.

## Adding an entry

Append `K-<n>` with: severity, the affected `path:line`, the observable symptom,
the blast radius, and a fix direction small enough to review in one sitting.
Prefer one entry per independently revertable fix.
