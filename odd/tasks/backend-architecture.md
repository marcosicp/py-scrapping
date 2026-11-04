# Feature: backend-architecture

| Field | Value |
| --- | --- |
| Status | in progress |
| Owner | el Gentleman (parent orchestrator) |
| Branch | `feat/backend-architecture` (local; **no push** — push/PR are the owner's call) |
| Created | 2026-11-04 |

## Problem

The Flask backend has no architecture, and the five scrapers cannot be run
individually in any reliable way. Evidence (all verified on `main@d310d6c`):

1. **One module does everything.** `api/routes.py` (195 lines) mixes the SPA root,
   a page render, five scraper-launch routes using **three different strategies**
   (inline, thread, thread + private event loop), two stop routes, the
   `/supermercados` query + grouping logic, and four dead routes (K-11).
2. **Persistence only works when a scraper runs *inside* the request.**
   Scrapers reach Mongo through `current_app.mongodb_client`. A plain
   `threading.Thread` has no application context (verified: `RuntimeError: Working
   outside of application context`). `/scraping-carrefour` starts a thread, so its
   `save_to_mongodb` always lands in the `except` branch and nothing is stored.
   Disco/HiperLibertad/SuperMami persist only because they block the request (K-9)
   — and Disco then 500s (K-4).
3. **Stop does not stop anything.** The stop routes build a *new* scraper instance
   and set `self.activeX = False` on it (an instance attribute); the running
   instance never sees it. Only two of five stop routes exist, both return `None`
   (K-10), and `frenar()` in `templates/scrape.html` references undefined
   variables (`categoria_`, `Http`), so the button never worked.
4. **No isolation or concurrency control.** Two `POST`s for the same supermarket run
   two scrapers that delete/insert the same slice of `productos`.
5. **Duplicated infrastructure.** The Chrome construction block (with the
   hardcoded `/usr/local/bin/chromedriver-141`, K-7), `save_to_mongodb`, the
   `scraping-message-<name>` channel string and a module-level `HTMLSession()` are
   copy-pasted into each scraper. `api/sockets.py` imports selenium,
   requests_html, bs4 and webdriver_manager that it never uses.
6. **K-18 is mis-diagnosed.** `HTML.arender` is a coroutine function
   (`inspect.iscoroutinefunction` → `True`) and all five call sites omit `await`
   (`scrap_disco.py:127`, `scrap_carrefour.py:111`, `scrap_changomas.py:100`,
   `scrap_supermami.py:35,61`). The coroutine is created and discarded, so
   `arender()` never runs and cannot raise. The scrapers parse the **un-rendered**
   HTML of a plain GET. The real blocker today is K-7 (driver/Chrome mismatch).

## Design

"Scalable" is read as **scalable code organization**: adding a supermarket is one
module plus one registry line; no route, template or service changes. Horizontal
runtime scaling is out of scope (see D5).

**D1 — Layers with one direction of dependency.**
`blueprints (HTTP) → services → repositories / scraper registry → infrastructure`.
Scrapers never import Flask, Mongo or SocketIO; they receive collaborators.

**D2 — Composition root.** `create_app(settings=None, *, repository=None,
scraper_registry=None, reporter=None)` builds every object once and stores them in
`app.extensions["lalistita"]` (`api/container.py`). Blueprints read from there.
Tests inject fakes; nothing relies on ambient `current_app` outside Flask views.

**D3 — Scraper contract.** `BaseScraper` (`slug`, `label`, `categories`,
`run(ctx)`) + `ScrapeContext` (`report`, `should_stop`, `sleep`, `save`,
`browser()`, `http`). A scraper is a pure collector: it asks the context to save,
report and sleep. Subclasses are registered explicitly in
`ScraperRegistry` (no filesystem magic).

**D4 — Per-supermarket runs.** `ScraperManager` owns the lifecycle: one active run
per supermarket (second `start` → `AlreadyRunning`, HTTP 409), independent
`threading.Event` per run for cooperative stop, a `RunStatus` per supermarket
(`idle/running/stopping/succeeded/failed/stopped`), different supermarkets run
concurrently. Every scraper is also drivable from a CLI (`python -m api.cli`)
because it does not depend on Flask.

**D5 — In-process threads behind a seam.** The runner is deliberately in-process
(one gunicorn worker + SocketIO `threading` mode, see AGENTS.md T-10). Job state is
per process, so `status`/`stop` must reach the process that runs the job — true
with `--workers 1`, which is what the repo already runs. `ScraperManager` is the
seam where a queue/worker (RQ/Celery) can be plugged later. Not built now.

**D6 — Replace without data loss (K-8).** `ProductRepository.replace_products`
reads the ids currently in the slice, **inserts the new documents first**, then
deletes exactly the old ids. A failed insert leaves the old data intact. An empty
result is a no-op (a broken scrape must never wipe a slice). Final state after a
successful run is identical to the legacy delete-then-insert.

**D7 — Keep every public contract.** `/supermercados` payload is byte-compatible
(Angular consumes it); socket channel `scraping-message-<slug>` keeps emitting a
plain string; `/scraping-<slug>` and `/scraping-<slug>-stop` stay as thin aliases
generated from the registry (now non-blocking, 409 when already running, stop
actually returns). New API lives under `/api/scrapers`.

**D8 — Chrome factory (K-7).** One `build_chrome(settings)`:
`CHROMEDRIVER_PATH` if set, otherwise Selenium Manager resolves a matching driver;
`CHROME_HEADLESS` opt-in (default off = today's visible window).

**D9 — Same HTTP fingerprint, no `requests-html`.** `requests_html.HTMLSession`
injects a Safari `User-Agent`; plain `requests` would send `python-requests/x.y`.
`api/scrapers/http.py` builds a `requests.Session` with the **same** UA string,
so the scrapers keep their request fingerprint. The never-executed `arender()`
statements are deleted. This closes K-18 and makes `requests-html` removable (T14).

**D10 — Ports are mechanical.** Scraping/parsing logic, selectors and category
lists are not rewritten. Only: stop flag → `ctx.should_stop()` at every loop
level, `notifyStatus` → `ctx.report`, `save_to_mongodb` → `ctx.save`, driver block
→ `ctx.browser()`, `_hTMLSession` → `ctx.http`, `time.sleep` → `ctx.sleep`.
ChangoMás (`async def` with no `await`) becomes a plain sync `run` and persists
through the repository like the others (its JSON-file dump is dropped; the
dashboard still ignores it — K-12 API half stays open).

## Target layout

```
app.py / main.py            entry points (unchanged contract: create_app, main:app)
api/
  config.py                 Settings.from_env()
  container.py              Services + get_services()
  sockets.py                socketio, configure_sockets, SocketIOReporter
  blueprints/               frontend.py  products.py  scrapers.py  legacy.py
  services/                 products.py  scraping.py (ScraperManager, RunStatus, errors)
  repositories/             products.py  (Protocol + MongoProductRepository)
  scrapers/                 base.py  registry.py  http.py  browser.py
                            disco.py carrefour.py changomas.py hiperlibertad.py supermami.py
  cli.py                    python -m api.cli list | run <slug> [--category X]
tests/                      pytest suite (fakes in tests/fakes.py)
```

## Non-goals

- Rewriting scraping logic, selectors or category lists.
- **Live scrape runs.** They need Chrome, network and a database; the agent does
  not run them. A user-supervised smoke run is the remaining check (see below).
- K-13 (auth/CORS/SECRET_KEY rotation), K-15, K-17 (aggregation + index), SPA
  deep-link fallback, frontend changes, deploy story, queue-based execution.
- Deciding the fate of `api/models/productos.py` (dead) or `templates/index*.html`.

## Tasks

- [ ] T1 Foundation: `Settings`, `create_app(settings=…)`, explicit packages, slim `api/sockets.py`, pytest harness, CI installs dev deps, AGENTS rule 5/§8 + runbook
- [ ] T2 `ProductRepository` + Mongo impl (`find_all`, insert-then-prune `replace_products`) + in-memory fake + tests (Mongo integration opt-in)
- [ ] T3 `ProductService` + `frontend`/`products` blueprints; `/`, `/scrape`, `/supermercados` leave `api/routes.py` (characterization test first)
- [ ] T4 Scraper core: `BaseScraper`, `ScrapeContext`, `ScraperRegistry`, `ScraperManager`, `ProgressReporter`, HTTP session builder (TDD, fake scrapers)
- [ ] T5 Scraper-control API `/api/scrapers…` + registry-generated legacy aliases + `api/container.py` + `SocketIOReporter`
- [ ] T6 Chrome factory (`CHROMEDRIVER_PATH`, `CHROME_HEADLESS`) + tests (K-7)
- [ ] T7 Port SuperMami (offline fake-HTTP behavior test)
- [ ] T8 Port HiperLibertad
- [ ] T9 Port Disco
- [ ] T10 Port Carrefour
- [ ] T11 Port ChangoMás
- [ ] T12 CLI runner `python -m api.cli`
- [ ] T13 `/scrape` page generated from the registry; working per-supermarket start/stop; relative URLs
- [ ] T14 Cleanup + docs: delete `api/routes.py` (K-11) and the `notifyStatus` shim, drop `requests-html` (K-18), reconcile AGENTS.md / repo-map / runbook / known-issues

## Verification plan

| Check | Method | Expected |
| --- | --- | --- |
| Behavior of new layers | `pytest` | green; each new behavior seen RED first |
| CI lint gate | `flake8 . --select=E9,F63,F7,F82` (excluding local-only dirs) | 0 |
| `/supermercados` unchanged | characterization test + old-vs-new compare on a scratch DB | identical payload |
| Replace semantics (K-8) | Mongo integration test on a throwaway DB | old docs survive a failed insert; replaced on success; empty = no-op |
| Isolation | manager tests | two slugs run concurrently; same slug → `AlreadyRunning` |
| Stop works | fake scraper blocked in `ctx.sleep` | returns promptly after `stop` |
| Pre-cancelled run is inert | contract test over every registered scraper | no browser, no network call |
| App boots under WSGI | `gunicorn main:app`: `GET /`, `/api/scrapers`, socket.io handshake | 200 / 200 / `0{"sid"…` |
| Live scrapes | **not run by the agent** | pending user-supervised smoke run |

## Review workload

Forecast ≈ 2,500–3,000 authored lines across 14 work units: **high** for a single
PR. Each task is one work-unit commit and a candidate slice. Suggested chained-PR
slices: (1) T1–T3 foundation, (2) T4–T6 scraper core + API + Chrome, (3) T7–T11
ports, (4) T12–T14 CLI, UI, cleanup. Running authored-line count is recorded below.

## Evidence

| Task | Commit | Lines (+/−) | Checks observed |
| --- | --- | --- | --- |
| — | — | — | — |
