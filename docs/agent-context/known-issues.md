# Known issues

Defect register for LaListita. Every entry was found by reading the code during
the agent-context bootstrap on `main@06b37b7` and is cited with `path:line`.

**Nothing here has been fixed.** Each entry is written to be liftable into its
own ODD task / work-unit commit. When you fix one, change its status to `fixed`,
add the commit sha, and leave the entry in place — the history is the point.

Entry point for agents: [`AGENTS.md`](../../AGENTS.md).

---

## Summary

| ID | Severity | Area | Status |
| --- | --- | --- | --- |
| [K-1](#k-1) | Critical | Runtime | open — SocketIO never initialized under WSGI |
| [K-2](#k-2) | Critical | Runtime | open — Mongo client only exists inside `__main__` |
| [K-3](#k-3) | High | Data | open — database name contradiction |
| [K-4](#k-4) | High | API | open — `/scraping-disco` thread misuse |
| [K-5](#k-5) | High | Deploy | open — Dockerfile runs a non-existent module |
| [K-6](#k-6) | High | Deploy | open — CI fails on every push |
| [K-7](#k-7) | High | Scrapers | open — ChromeDriver 141 vs Chrome 156 |
| [K-8](#k-8) | High | Data | open — Carrefour deletes before inserting |
| [K-9](#k-9) | Medium | API | open — blocking scraper routes |
| [K-10](#k-10) | Medium | API | open — stop routes return `None` → 500 |
| [K-11](#k-11) | Medium | API | open — dead `/supermercado-*` routes |
| [K-12](#k-12) | Medium | Data | open — ChangoMás never reaches MongoDB or the API |
| [K-13](#k-13) | Medium | Security | open — unauthenticated scraper control + wide-open CORS |
| [K-14](#k-14) | Medium | Tooling | open — broken `.venv` |
| [K-15](#k-15) | Medium | Tooling | open — global Angular CLI too old |
| [K-16](#k-16) | Low | Hygiene | open — dead modules and duplicated build output |
| [K-17](#k-17) | Low | Perf | open — full-collection scan on every API call |

---

## <a id="k-1"></a>K-1 · SocketIO is never initialized outside `python app.py`

**Severity:** Critical when deployed; invisible locally.

`configure_sockets(app)` is called at `app.py:26`, inside
`if __name__ == '__main__':`. Any WSGI server (gunicorn, uWSGI, Cloud Run,
Heroku, App Engine) imports `app` as a module, so `__main__` never runs and
`socketio.init_app(app)` never happens.

**Impact:** every `notifyStatus()` call (`api/sockets.py:48`) emits on an
uninitialized SocketIO object; `/scrape` shows nothing. Failure is silent — no
exception surfaced to the user.

**Fix direction:** move `configure_sockets(app)` to module scope, or convert
`app.py` into a `create_app()` factory and call it from a real WSGI entry point.
The factory is the shape K-2 needs anyway; do both in one work unit.

## <a id="k-2"></a>K-2 · `current_app.mongodb_client` does not exist under WSGI

**Severity:** Critical when deployed.

The client is attached at `app.py:32` and `app.py:42`, both inside the
`__main__` block. Consumers all read `current_app.mongodb_client`:

- `api/routes.py:93`
- `api/scrapers/scrap_disco.py:33`
- `api/scrapers/scrap_carrefour.py:38`
- `api/scrapers/scrap_hiperlibertad.py:32`
- `api/scrapers/scrap_supermami.py:101`

**Impact:** under gunicorn these raise `AttributeError`. `/supermercados` catches
it in its `except` (`api/routes.py:137`) and returns an empty payload, so the
breakage looks like "no data" rather than "misconfigured app". The scrapers do
not catch it and fail mid-run.

**Fix direction:** same factory move as K-1, or a `@app.before_first_request` /
`before_request` hook that creates the client lazily.

## <a id="k-3"></a>K-3 · Two database names; the one that is set is dead

**Severity:** High (confusion cost, not data loss).

`app.py:33` and `app.py:43` set `app.database = client["lalistita"]`. Every
consumer instead uses `client.lalistitadev` (`api/routes.py:94` and the four
scrapers). `app.database` is never read.

**Impact:** anyone reading `app.py` believes the database is `lalistita`. It is
not. Data written by scrapers and read by the API lives in `lalistitadev`.

**Fix direction:** delete `app.database` (dead code) and centralize the database
name in config, e.g. `MONGODB_DB` with default `lalistitadev`.

## <a id="k-4"></a>K-4 · `/scraping-disco` calls the scraper inline and then crashes

**Severity:** High.

```python
Thread(target = scrape_service.scrape_disco(categoria),).start()   # api/routes.py:34
```

`scrape_disco(categoria)` is **called**, not referenced. The whole scrape runs
synchronously inside the HTTP request, returns `None`, and then
`Thread(target=None).start()` raises `TypeError`. Compare the correct form two
routes down (`api/routes.py:62`).

**Impact:** the request blocks for the entire Disco scrape (many minutes, five
paginated subcategories, `arender(sleep=8)` each) and then returns 500. Disco has
no working start route at all.

**Fix direction:** `Thread(target=scrape_service.scrape_disco, args=(categoria,)).start()`
— and give Disco the same start/stop pair the other scrapers have.

## <a id="k-5"></a>K-5 · Docker image builds, then crashes on start

**Severity:** High.

`Dockerfile:22` → `CMD exec gunicorn ... main:app`. There is no `main.py` in the
repository (`git ls-files | grep '^main.py'` → empty). Nothing produces or imports
`main`.

**Impact:** the image builds successfully and the container dies immediately at
boot. Combined with K-1/K-2, even pointing it at `app:app` would deploy a service
with dead realtime and no database.

**Fix direction:** introduce the `main.py` (or `wsgi.py`) entry the factory from
K-1/K-2 exposes, and point the `CMD` at it. Also decide the single deployment
story and delete the others (`Procfile`, `gunicorn_config.py`, `app.yaml`,
`manifest.yml`).

## <a id="k-6"></a>K-6 · CI is red on every push because there are no tests

**Severity:** High (destroys the signal value of CI).

`.github/workflows/python-app.yml` ends with `pytest`. The repo has zero Python
test files and does not even list pytest in `requirements.txt` (the workflow
installs it ad hoc). Pytest exits **5 — no tests collected**, which the job
treats as failure.

**Impact:** a permanently red check trains everyone to ignore CI. The only real
gate today is `flake8 --select=E9,F63,F7,F82` (syntax + undefined names); the
second flake8 invocation is `--exit-zero`.

**Fix direction:** choose one — either add a real test suite (start with
`name_parse` and `remove_duplicates_by_key`, both pure functions in
`api/helpers.py`), or gate the step (`pytest … || [ $? -eq 5 ]`). Do not leave it
red.

## <a id="k-7"></a>K-7 · ChromeDriver pinned to 141, Chrome is 156

**Severity:** High (all scraping is dead on this machine).

`Service('/usr/local/bin/chromedriver-141')` appears in four of the five
scrapers (`scrap_disco.py:65`, `scrap_carrefour.py:75`, `scrap_changomas.py:35`,
`scrap_hiperlibertad.py:64`). **SuperMami has no driver** — it uses
`requests_html` only, despite importing selenium modules it never calls.

Measured: `/usr/local/bin/chromedriver-141` exists; `Google Chrome
156.0.8078.80` is installed.

**Impact:** every scraper fails with `session not created: This version of
ChromeDriver only supports Chrome version 141`.

**Fix direction:** stop hardcoding an absolute path. Read a `CHROMEDRIVER_PATH`
env var with a sane fallback, centralize driver construction in one helper
instead of five copies, and document the version-match requirement. Note that
`webdriver-manager` is already a declared dependency but bypassed everywhere.

## <a id="k-8"></a>K-8 · Carrefour replaces a whole category before scraping

**Severity:** High (irreversible data loss on a bad run).

`api/scrapers/scrap_carrefour.py:43`:

```python
collection.delete_many({"supermercado": "Carrefour", "categoria": category_name})
```

then `insert_many` at `:52`.

**Impact:** if the scrape fails after the delete — driver version mismatch (K-7),
a site change, a network blip — the category is left empty in production. No
transaction, no staging collection, no backup.

**Fix direction:** write to a staging collection or accumulate first and swap
after a non-empty verified result. At minimum, never delete before you have the
replacement data in memory.

## <a id="k-9"></a>K-9 · Two scraper routes block the worker

**Severity:** Medium.

`/scraping-hiperlibertad` (`api/routes.py:38`) and `/scraping-supermami`
(`api/routes.py:46`) call the scraper inline. Only `/scraping-carrefour` and
`/scraping-changomas` spawn a thread.

**Impact:** with gunicorn's default of 1–2 workers, two concurrent scrape requests
exhaust the pool and the whole app stops answering until the scrapes finish.

**Fix direction:** one helper `start_scraper_async(scraper, *args)` used by all
five routes, plus the asyncio wrapper only for ChangoMás.

## <a id="k-10"></a>K-10 · Stop routes return `None`

**Severity:** Medium.

`/scraping-supermami-stop` (`api/routes.py:53`) and `/scraping-changomas-stop`
(`api/routes.py:84`) end after the `scrape_*_stop()` call with no `return`.

**Impact:** Flask raises `TypeError: The view function did not return a valid
response` → HTTP 500, even though the stop flag was set successfully. Callers
see failure and may retry.

**Fix direction:** return the same `json.dumps({'success': True}), 200, {...}`
envelope the POST routes use.

## <a id="k-11"></a>K-11 · Dead `/supermercado-*` routes read files that cannot exist

**Severity:** Medium (confusing, not harmful).

`api/routes.py:150-184` defines four routes that `open('carrefour.json')`,
`'disco.json'`, `'hiperlibertad.json'`, `'supermami.json'` — none of which exist
in the repo (`*.json` is gitignored at `.gitignore:56`), and afterwards ignore the
parsed data entirely by returning `static/index.html`.

**Impact:** any hit is a 500; readers assume per-supermarket pages exist.

**Fix direction:** delete the four routes. If per-supermarket views are wanted,
serve them from Mongo through `/supermercados?supermercado=…`.

## <a id="k-12"></a>K-12 · ChangoMás writes only to local JSON files

**Severity:** Medium (silent data black hole).

`api/scrapers/scrap_changomas.py:147` dumps to `.changomas/almacen/<file>.json`
and never calls a `save_to_mongodb`. `/supermercados` also has no `changomas`
branch (`api/routes.py:106-115`).

**Impact:** ChangoMás appears in the README, the UI and the route table but its
data is never queryable. `.changomas/` is gitignored, so the data is also
ephemeral — gone on redeploy and invisible on Cloud Run.

**Fix direction:** add `save_to_mongodb` following the other scrapers, and a
`changomas` group + count in `/supermercados`. Then update the README table.

## <a id="k-13"></a>K-13 · Anyone can start a scrape; CORS is wide open

**Severity:** Medium.

`app.py:15` → `CORS(app)` with no origins restriction. All `/scraping-*` routes
are unauthenticated and `POST`/`GET` from any origin. `SECRET_KEY = 'secret!'`
(`app.py:18`).

**Impact:** a third-party page can trigger scrapes against the operator's IP and
mutate MongoDB (K-8 makes one of them destructive). Also an open relay for
resource abuse.

**Fix direction:** restrict `CORS` to known origins and put the scraper-control
routes behind a token (`Authorization: Bearer $ADMIN_TOKEN`). Read `SECRET_KEY`
from the environment.

## <a id="k-14"></a>K-14 · `.venv` is broken and blocks every Python command

**Severity:** Medium (first-run blocker).

`pyvenv.cfg` records `home = /Library/Frameworks/Python.framework/Versions/3.11`,
but the interpreter inside the venv fails:
`.venv/bin/pip: … bad interpreter: No such file or directory`.

**Impact:** `source .venv/bin/activate && pip …` and `python app.py` both fail.
An agent that assumes the venv is usable burns turns on a broken symlink.

**Fix direction:** this is a local-state issue, not a repo defect — but it should
be asserted. `.venv/` is already gitignored, so the reproducible path is: delete,
`python3 -m venv .venv`, `pip install -r requirements.txt`. Optionally document
the interpreter in a `.python-version`.

## <a id="k-15"></a>K-15 · The global Angular CLI cannot build this workspace

**Severity:** Medium (first-run blocker).

`ng version` → `Angular CLI: 14.2.10`, `Node: 26.7.0 (Unsupported)`. The workspace
is Angular **19.2.19** with the `application` builder
(`@angular-devkit/build-angular:application`), which CLI 14 does not have.

**Impact:** `ng build` / `ng serve` from the global CLI fail with builder
resolution errors. `package.json` scripts are fine *after* `npm install`, because
they resolve `node_modules/.bin/ng`.

**Fix direction:** document `npx ng` / `node_modules/.bin/ng` as the only
supported invocation, and pin Node via `.nvmrc` / `engines` (`package.json` has
neither). Node 26 is untested by Angular 19.

## <a id="k-16"></a>K-16 · Dead modules, duplicated build output, repeated imports

**Severity:** Low (noise that misleads readers).

- `api/models/productos.py` — `from pymongo import pymongo` then
  `pymongo.Document` / `pymongo.StringField`. Those are mongoengine APIs; the
  module cannot work. Imported by nothing.
- `templates/index.html`, `index3.html`, `index4.html`, `indexa.html` — Angular
  build output committed as Jinja templates (`data-critters-container`). No route
  renders them.
- `templates/index2.html` — legacy server-rendered page, never rendered.
- `gunicorn_config.py`, `app.yaml`, `manifest.yml` — orphaned deploy configs (see
  K-5).
- `api/routes.py:1` and `:6` both `from threading import Thread`; `redirect_url()`
  (`:16`) is defined and never used.

**Fix direction:** delete. Separately, decide whether `static/` should stay
committed at all — see the note in `runbook.md` §4; an uncommitted build output
with a deploy-time build step would remove a whole class of stale-bundle bugs.

## <a id="k-17"></a>K-17 · Every API call scans the whole collection

**Severity:** Low now, scales badly.

`api/routes.py:98` → `list(collection.find({}, {"_id": 0}))`, then Python-side
grouping, O(n²)-ish dedupe (`api/helpers.py:3` loop with `not in`), and a sort.
No indexes are created anywhere.

**Impact:** `/supermercados` loads every product of every supermarket into memory
per request and runs dedupe in Python. Fine for a few thousand rows, not for a
full catalog.

**Fix direction:** aggregate in Mongo (`$group` / `$match` on `supermercado`), add
a compound index on `(supermercado, name)`, and paginate.

---

## Minor observations (not filed)

- `datetime.utcnow()` in `save_to_mongodb` is deprecated from Python 3.12; prefer
  `datetime.now(timezone.utc)`.
- `name_parse`'s regex includes bare `m` as a unit (`api/helpers.py:17`), so a
  name containing "100 m" can be mis-parsed. It also strips only the first match.
- Duplicate suppression is substring-based
  (`if not any(element['name'] in new['name'] …)`), which drops legitimately
  distinct products whose names contain another product's name.
- Only ChangoMás closes its driver in a `finally`; the other four leak the browser
  process on exception.
- `requirements.txt` lists `bs4` next to `beautifulsoup4` — the meta-package is
  redundant.

## Adding an entry

Append `K-<n>` with: severity, the affected `path:line`, the observable symptom,
the blast radius, and a fix direction small enough to review in one sitting.
Prefer one entry per independently revertable fix.
