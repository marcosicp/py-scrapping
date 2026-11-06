# Feature: render-docker-deploy

| Field | Value |
| --- | --- |
| Status | done — implemented, verified locally, committed and merged to `main` |
| Owner | el Gentleman (parent orchestrator) |
| Branch | `feat/render-docker-deploy` |
| Created | 2026-11-06 |

## Problem

The Render deploy fails before it starts, and the log misleads:

```
ERROR: Ignored the following versions that require a different python version:
       4.19.0 Requires-Python >=3.11
ERROR: Could not find a version that satisfies the requirement pymongo==4.19.0
       (from versions: ..., 4.18.3)
```

`pymongo==4.19.0` exists and declares `Requires-Python: >=3.11` on PyPI;
`4.18.3` declares `>=3.9`. pip only lists candidates compatible with the running
interpreter, and it listed `4.18.3` as the ceiling — so **the build ran on Python
3.9 or 3.10**, not on the 3.15 the repo declares everywhere.

Two independent causes, both Render-native-runtime specific:

- **D1 — Render's native Python runtime cannot install 3.15.** Render's own
  docs: version precedence is the `PYTHON_VERSION` env var, then a root
  `.python-version`, then the *service's creation-date default*; unreleased
  versions are only available through Docker. Neither `.python-version`
  (`3.15.2`) nor the vestigial `runtime.txt` (Render does not read it — that's a
  Heroku/Cloud Foundry artifact) gets Render a 3.15 interpreter.
- **D2 — the native runtime never builds the SPA.** `static/` is gitignored
  build output (`api/blueprints/frontend.py:20` answers 503 without it) and a
  native Python build runs `pip install` only. A "green" deploy from a native
  runtime therefore serves a 503 at `/`.

So the fix is not a pin bump. It is to stop relying on Render's Python runtime
and let the repo's own `Dockerfile` define the environment: the image already has
a `node:24-alpine` frontend stage that produces `static/`, and a
`python:3.15-slim` runtime stage (that tag exists on Docker Hub; verified).

## Design decisions

- **D3 — Docker, not a downgraded interpreter.** Pinning Render to 3.14 plus a
  hand-written npm build step would work but leaves production and the repo
  disagreeing about the interpreter. The Dockerfile is the single source of
  truth for the deployed environment, and it is an image a developer can build
  and run locally (CI has no docker step).
- **D4 — keep `--workers 1 --threads 8`.** `ScraperManager` keeps run state
  in-process (single-flight per supermarket), and SocketIO runs in `threading`
  mode (T-10). More gunicorn workers would give each worker its own run state
  and its own SocketIO clients.
- **D5 — Chromium ships in the image, behind a build arg.** The scrapers are the
  app's reason to exist; without a browser every `POST /api/scrapers/<slug>/start`
  dies with "chromedriver not found". Render has no display, so the container
  also needs `CHROME_HEADLESS=1`.
- **D6 — a `CHROME_BINARY` setting instead of guessing the browser binary.**
  Debian's chromium lives at `/usr/bin/chromium`, and without this setting the
  binary is guessed heuristically: Selenium Manager probes candidate paths
  (chromedriver falls back to well-known names), and a guess that does not
  match the image fails the session with `session not created` /
  binary-not-found. Pinning `binary_location` through `Settings.chrome_binary`
  removes the guess and keeps AGENTS.md hard rule 6 intact: the driver comes
  from `api/scrapers/browser.py`, driven by configuration.
- **D7 — `render.yaml` as the deploy contract.** The failure above came from
  service settings living only in a dashboard. A blueprint makes the environment
  reviewable in the repo, and `sync: false` keeps secrets out of Git.

## Tasks

| # | Task | Status |
| --- | --- | --- |
| T1 | `CHROME_BINARY` setting in `api/config.py` + `build_chrome` + tests (RED→GREEN) | done |
| T2 | `Dockerfile`: `PORT` default, chromium runtime deps behind `INSTALL_CHROMIUM`, `EXPOSE`, stale CMD comment | done |
| T3 | `render.yaml`: docker runtime, `healthCheckPath: /`, env vars (`SECRET_KEY` generated, `MONGODB_URI` prompted) | done |
| T4 | `docs/agent-context/deploy-render.md` + AGENTS.md links | done |
| T5 | Verification: pytest, `docker build`, container smoke at `/`, `/scrape`, `/api/scrapers` | done |
| T6 | Repair `adminpro/package-lock.json` so `npm ci` works inside the image (found during T5) | done |

## Verification evidence (observed, not inferred)

- T1 RED: `pytest tests/test_config.py tests/test_browser.py -q` → 4 failed
  (`Settings has no attribute 'chrome_binary'`). GREEN: 32 passed.
- Full suite after T1–T4: **401 passed, 9 skipped** (baseline 396 + 5 new tests).
- `flake8 api tests --select=E9,F63,F7,F82 --count` → 0.
- T6: the first `docker build` failed in the *unchanged* frontend stage —
  `npm ci` reported `Missing: @emnapi/core@1.11.3, @emnapi/runtime@1.11.3,
  @emnapi/wasi-threads@1.2.3`. The lockfile was regenerated with the same npm
  the image uses (`node:24-alpine`, npm 11.19.1) via `npm install
  --package-lock-only --ignore-scripts`; the diff is 189 insertions / 94
  deletions and contains no runtime library bumps (hoisted
  `picomatch`/`chokidar`/`readdirp` nesting plus the three `@emnapi` entries).
- `docker build -t lalistita:verify .` → success, **988 MB**;
  `--build-arg INSTALL_CHROMIUM=0` → **243 MB**.
- Container smoke (`-e PORT=8080`, no reachable Mongo): `GET /` 200,
  `GET /scrape` 200, `GET /api/scrapers` 200 with the five slugs; image runs
  `Python 3.15.2` and carries `/app/static/index.html`,
  `/usr/bin/chromium`, `/usr/bin/chromedriver`.
- Selenium inside the container with `CHROME_HEADLESS=1`,
  `CHROME_BINARY=/usr/bin/chromium`, `CHROMEDRIVER_PATH=/usr/bin/chromedriver`:
  launched Chromium `156.0.8078.79` headless and quit cleanly — D5/D6 verified
  for real, not just statically.

### Not verified (manual, by design)

- A live Render deploy and its `onrender.com` URL.
- A live Atlas connection and a real scrape from a datacenter IP.

## Independent verification (fix round)

An independent read-only verifier reviewed the merged slice and returned
**PASS WITH NITS**. History of its confirmed findings and the fix round that
closed them:

- **The `google-chrome` mechanic was refuted.** Four places (and the
  Dockerfile comment) claimed Selenium "only looks for `google-chrome` in
  PATH". Grepping selenium 4.52.0 shows zero occurrences of that token in any
  Python file, and the vendored `selenium-manager` binary embeds many candidate
  paths, `/usr/bin/chromium` among them. The real mechanic is heuristic:
  Selenium Manager probes candidate paths and chromedriver falls back to
  well-known names, and a guess that does not match the host fails with
  `session not created` / binary-not-found. That is what the corrected wording
  now says, in `api/config.py`, `api/scrapers/browser.py`,
  `docs/agent-context/deploy-render.md` §4, the Dockerfile comment and D6.
- **The lockfile commit message over-stated.** `f893ca8` said the lockfile
  resync carried "no library version changes", but it also carries a
  dev-only nested `picomatch 2.3.1 → 2.3.2` bump plus re-hoisted
  `chokidar`/`readdirp` entries. No production dependency changed.
- **Test-count drift closed.** The baseline moved 396 → 401 (the slice added
  5 tests); AGENTS.md and `docs/agent-context/runbook.md` now say the observed
  **401 passed / 9 skipped**.
- **`docs/agent-context/runbook.md` contradiction closed.** §6 still claimed
  the deploy path was undecided and "the image has never been built here",
  which this document's own evidence refuted. §6 now states Render + Docker as
  the chosen path, records the image build and container smoke as verified
  (988 MB / 243 MB, all three probes 200), and keeps only the live Render
  deploy as unverified.
- **Still unverified after this round:** a live Render deploy and its
  `onrender.com` URL, and a real Atlas connection — manual by design.

## Commit evidence

| Commit | Work unit |
| --- | --- |
| `540f5d3` | `feat(container)` — Dockerfile (chromium, PORT default, CMD rationale), `CHROME_BINARY` setting, tests |
| `f893ca8` | `fix(build)` — `adminpro/package-lock.json` resynced with the image's npm |
| `0f38ebc` | `chore(deploy)` — `render.yaml`, `docs/agent-context/deploy-render.md`, AGENTS.md, this document |

## Verification plan

- `pytest` full suite stays green (baseline 401 passed / 9 skipped).
- `docker build -t lalistita:local .` succeeds and the frontend stage emits
  `static/index.html` into the runtime image.
- `docker run -p 8080:8080 -e PORT=8080 lalistita:local` answers `200` at `/`
  and `/scrape`, and `GET /api/scrapers` lists the five slugs **without** a
  reachable Mongo (the control API reads the registry, not the database).
- What is **not** covered: real scraping against supermarket APIs from a
  datacenter IP, and the live Atlas connection. Both are stated as manual.

## Open risks

- Render free plan is 0.1 CPU / 512 MB; Chromium will not survive a real scrape
  there. Scraping needs at least `1c-2g` (matching `deploy-render.md` §7 and
  `render.yaml`).
- Datacenter IPs are frequently blocked by the chains' WAFs. A container that
  runs Chrome is necessary, not sufficient, for a successful scrape from Render.
