# Feature: backend-architecture

| Field | Value |
| --- | --- |
| Status | done — 20 commits on the branch, none pushed |
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

- [x] T1 Foundation: `Settings`, `create_app(settings=…)`, explicit packages, slim `api/sockets.py`, pytest harness, CI installs dev deps, AGENTS rule 5/§8 + runbook
- [x] T2 `ProductRepository` + Mongo impl (`find_all`, insert-then-prune `replace_products`) + in-memory fake + tests (Mongo integration opt-in)
- [x] T3 `ProductService` + `frontend`/`products` blueprints; `/`, `/scrape`, `/supermercados` leave `api/routes.py` (characterization test first)
- [x] T4 Scraper core: `BaseScraper`, `ScrapeContext`, `ScraperRegistry`, `ScraperManager`, `ProgressReporter`, HTTP session builder (TDD, fake scrapers)
- [x] T5 Scraper-control API `/api/scrapers…` + registry-generated legacy aliases + `api/container.py` + `SocketIOReporter`
- [x] T6 Chrome factory (`CHROMEDRIVER_PATH`, `CHROME_HEADLESS`) + tests (K-7)
- [x] T7 Port SuperMami (offline fake-HTTP behavior test)
- [x] T8 Port HiperLibertad
- [x] T9 Port Disco
- [x] T10 Port Carrefour
- [x] T11 Port ChangoMás
- [x] T12 CLI runner `python -m api.cli`
- [x] T13 `/scrape` page generated from the registry; working per-supermarket start/stop; relative URLs
- [x] T14 Cleanup + docs: delete `api/routes.py` (K-11) and the `notifyStatus` shim, drop `requests-html` (K-18), reconcile AGENTS.md / repo-map / runbook / known-issues

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

## Notes (running)

- Transitional (T3 → T7–T11): `/supermercados` reads through `settings.mongodb_db`
  while the not-yet-ported scrapers still write to the hardcoded `lalistitadev`.
  Identical with the default `MONGODB_DB`; resolved as each scraper is ported.
- Doc citations of `api/routes.py:<line>` for routes that did not move are stale
  (the file shrinks with every task); they are re-pointed once, in T14.
- Process: commit first, then `gentle_review assess` with
  `{"baseRef":"<previous unit>","committedOnly":true}` (the working-tree assess is
  `unassessable` while untracked files exist). Plan so far: medium risk, writer
  self-verification stands, no separate verifier required.

- Follow-ups found while porting (deliberately NOT fixed in the port commits):
  - SuperMami keeps `totalPages` computed and unused, bs4 `findAll`/`text=` deprecation
    warnings, and the legacy 2-page cap (`MAX_PAGES = 2`).
  - HiperLibertad's legacy status guard `status_code == 200 | status_code == 206` is
    chained-comparison nonsense (`200|200 == 200` then `200 == 206`), so the legacy
    scraper has never collected a single product; T8 fixes it deliberately.
  - The legacy HiperLibertad driver is created and never used; T8 drops it.
  - `tests/test_scraper_supermami.py` imports the legacy module for the differential, so
    those tests must be deleted in the same commit that deletes it (T14).

## Evidence

| Task | Commit | Lines (+/−) | Checks observed |
| --- | --- | --- | --- |
| T1 | `88736b2` | +304/−84 | RED (ImportError `api.config`) → GREEN `14 passed`; flake8 CI gate `0`; route count 15 = baseline; independent verification PASS-WITH-NOTES (2 minor notes fixed: env-sensitive test, stale `app.py:18` doc cite). Verifier fallback: `jd-judge-a` (gentle-ai-verify pin was fixed on disk but the running session still caches the old model until Pi reloads agents) |
| T2 | `6790b1e` | +495 total (6 paths) | RED (ModuleNotFoundError) → GREEN `34 passed, 9 skipped`; opt-in real MongoDB run on a throwaway `lalistita_test_*` DB `29 passed`, no DB left behind; flake8 gate `0`; native assess on the committed range: risk medium, writer self-verification stands, no separate verifier required |
| T3 | `df6a442` | +685 total (16 paths) | RED (ModuleNotFoundError / TypeError) → GREEN `55 passed, 9 skipped`; route set identical before/after; **old-vs-new differential on 600 randomized datasets: byte-identical responses (275 success, 325 fallback), 0 mismatches**; flake8 gate `0`; native assess: risk medium, no separate verifier required |
| T4 | `052aeda` | +1806 total (10 paths, test-heavy) | RED (ModuleNotFoundError) → GREEN; review found 3 manager defects (stale `running` after fast finish, SystemExit leaving a slug RUNNING, ghost RUNNING when `thread.start()` fails) → fixed test-first (versioned serialized notifications); `127 passed, 9 skipped`; manager/context suites looped 15× green; ad-hoc 8-thread hammer 187k ops: 0 errors, 0 leaked threads, last delivered state == final state; flake8 gate `0`; no flask/pymongo/socketio/selenium imports in the core; native assess: medium, no separate verifier |
| T5 | `7ff8ff2` | +832 total (14 paths) | RED (ImportError `SocketIOReporter`, TypeError `scraper_registry`; 22 failed) → GREEN `152 passed, 9 skipped`; API suites looped 15× green; route set identical except the 4 new `/api/scrapers` rules; flake8 gate `0`; native assess: medium, no separate verifier required |
| T6 | `a4bbd18` | +317 total (8 paths) | writer reported RED (AttributeError/TypeError/ModuleNotFoundError) → GREEN; orchestrator re-verified after the owner's pause: `175 passed, 9 skipped`, flake8 gate `0`, F401/F811/F821 clean, diff read (lazy selenium import, Service(path) only when configured, headless opt-in); native assess: medium, no separate verifier required |
| T7 | `742e63e` | +639/−26 (10 paths) | contract tests added for every port; `194 passed, 9 skipped`; 15× loops green; legacy-vs-port differential over canned HTML (documents equal after `_id`/`scraped_at`; empty-page request sequences pinned); orchestrator audit raised one suspected `countPages` fidelity gap — measured and **refuted** (the legacy `continue` was already preserved; a mutation run now kills it); flake8 gate `0`; native assess: medium |
| T8 | `e9de3c7` | +807/−? (6 paths) | two deliberate fixes: the legacy status guard `status_code == 200 | status_code == 206` is a chained comparison that is False for every status (the differential proves the legacy path made 14 requests and stored 0 documents), and the dead Chrome driver is gone; `218 passed, 9 skipped`; suite runtime 13.2 s → 1.1 s after the 1 s rate-limit wait became a recorded request; container test now registry-driven; flake8 gate `0`; native assess: medium |
| T9 | `4665c1c` | 5 paths | mechanical port; three documented decisions (page 1 stays uncollected, errors propagate, dead `arender` deleted); differential pins driver visits, page URLs and documents; K-4 closed with its route; `239 passed` |
| T10 | `5a3bc9c` | 5 paths | both legacy collection paths kept (Path A json-LD over HTTP without `unidad`; Path B driver + `name_parse`); **legacy Path A never worked** (`"Scrapeando categoria: " + dict` → TypeError) and the port fixes the message; empty results no longer wipe the slice; two differentials; `262 passed` |
| T11 | `9d9248d` | 5 paths | last port; async-with-no-await → sync; Selenium waits behind a lazy testable seam; **K-12 scraper half done** (`.changomas/*.json` → repository, `categoria=almacen`, `subcategoria=<section>`), API half open; all five registered, so every `/scraping-<slug>(-stop)` alias exists and Disco/HiperLibertad gained stop endpoints; `280 passed`, suite 1.4 s |
| T12 | `da9f375` | 4 paths | `python -m api.cli list` and `run <slug> [--category]` with exit codes 0/1/2/3 and Ctrl+C → cooperative stop; 9 offline CLI tests; `run ghost` exits 3 with a clean error |
| T13 | `c98b200` | 4 paths | `/scrape` generated from the registry (one card per scraper), relative URLs, the broken `frenar()` fixed, 409 surfaced in the card, one `scraper-status` listener |
| T14a | `30b20cb` | 22 paths (5 files deleted) | `api/routes.py` (K-11), the five `scrap_*.py`, `notifyStatus` and the differentials deleted; `requests-html`, `lxml_html_clean`, `webdriver-manager` dropped (K-18); 291 → 281 tests, green; route set 22 → 18 |
| T14b | `10fc059` | 6 paths | docs reconciled: AGENTS (§2/§3/§4/§5/§6/§7/§8), known-issues (11 dispositions, 36 citations re-verified), repo-map (layers + 18 routes), runbook, copilot pointer |

## Close

**Done:** the backend has layers (blueprints → services → repositories/registry →
infrastructure) with one composition root, and each supermarket is an independent,
individually runnable scraper: `POST /api/scrapers/<slug>/start|stop`,
`GET /api/scrapers[/<slug>]`, the legacy `/scraping-<slug>` aliases, the registry-driven
`/scrape` page and `python -m api.cli run <slug>`. Adding a supermarket is one module
plus one registration line.

**Verified:** 281 tests green (`pytest`, ~1.3 s), flake8 CI gate 0, F401/F811/F821 0,
18 routes, `/scrape` renders five cards, CLI lists five scrapers. Behaviour-preservation
evidence: an old-vs-new differential on 600 randomized `/supermercados` payloads (0
mismatches) and, before the legacy modules were deleted, legacy-vs-port differentials
over identical canned HTML/JSON for all five scrapers.

**Not verified (requires the owner):** no live scrape was run — every scraper needs
Chrome, the real sites and a real MongoDB. The first supervised smoke run should be
`python -m api.cli run hiperlibertad` (the only one that needs no browser) and then
`disco`, watching `CHROME_HEADLESS=1` behaviour and the documents landing in Mongo.

**Follow-ups (deliberately out of scope):**
- README is still stale (AGENTS rule 4): it documents Angular 16/Python 3.11 and the
  old scraper list.
- K-12 API half: `/supermercados` and the dashboard still ignore the `ChangoMas` group.
- Disco never collects page 1; SuperMami caps at 2 pages; Carrefour Path A stores no
  `unidad`. Each needs a real run to validate a fix.
- K-13 (auth on the control routes, CORS, `SECRET_KEY` rotation), K-15, K-17
  (aggregation + indexes) remain open.
- `api/models/productos.py`, `templates/index*.html`, `gunicorn_config.py`,
  `app.yaml`, `manifest.yml` are still dead files.
- A queue-based runner (RQ/Celery) is the natural next step if the app ever needs more
  than one worker; the `ScraperManager` seam is where it plugs in.
