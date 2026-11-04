# Feature: uncommit-static-build-output

| Field | Value |
| --- | --- |
| Status | in progress |
| Owner | el Gentleman (parent orchestrator) |
| Branch | `main` (owner commits to main locally) |
| Created | 2026-11-03 |

## Problem

`static/` is committed Angular build output: **662 tracked files, 17 MB**.

Two independent costs, both measured:

1. **It makes review impossible.** A single rebuild produces a 3.8 MB diff of
   minified bundles (`main-*.js` 1.22 MB × two versions, `styles` 441 KB × two,
   `scripts` 202 KB × two). Native review rejected the last candidate with
   `lens_context_budget_exceeded` in preflight: 3.9 MB total, of which 97.7% was
   build output and only 92.6 KB was the actual work. The bundle alone exceeds the
   reviewer context budget, so no partition of history can rescue it.
2. **`git status` stops meaning anything.** Every build rewrites hundreds of
   files, and stale hashes accumulate unless someone deletes them by hand.

## Safety check performed first

Before untracking anything, `static/` was proven fully reproducible from tracked
sources:

| Check | Result |
| --- | --- |
| Files in `static/assets` with no origin in `adminpro/src/assets` | **0** |
| `adminpro/src/assets` tracked | 655 (the extra one is `.gitkeep`) |
| `static/favicon.ico` source | `adminpro/src/favicon.ico` ✅ |
| The one `static/media/` file | `error-bg-X7AJZDAK.jpg`, emitted by the builder from `adminpro/src/assets/images/background/error-bg.jpg`, referenced by three CSS files ✅ |
| Files produced by a clean build but missing from `static/` | **0** |

Nothing is lost by untracking.

## Design decisions

- **D1 — `static/` stays the build destination.** Flask keeps serving
  `<repo>/static/index.html`; only tracking changes. Moving the output to
  `adminpro/dist` and rewiring `static_folder` would be a much larger blast radius
  for zero benefit.
- **D2 — Track `adminpro/package-lock.json`.** Coupled requirement, not
  optional: the image build now runs `npm ci`, which needs a lockfile. Without
  it the frontend build is non-reproducible and CI cannot detect drift. This also
  closes the pending item from the Angular migration.
- **D3 — Multi-stage Docker build.** A `node:24-alpine` stage builds the bundle
  and the Python stage copies `static/` from it. Node 24 satisfies
  `@angular/cli@21`'s `>=24.0.0`.
- **D4 — Fail loudly, with instructions.** Without the bundle, `/` used to 404
  with no explanation. `api/routes.py` now returns **503** and prints the exact
  build command. This is the failure mode of the change itself, so it ships with
  it.
- **D5 — History is not rewritten.** The 17 MB stay in past commits. This unit
  stops *growing* the problem; it does not shrink the clone. Shrinking would need
  `filter-repo` plus a force-push, which is a separate decision with collateral
  damage (forks, open PRs).

## Non-goals

- K-5 (`Dockerfile` CMD still targets a non-existent `main:app`). Adjacent and
  known; fixing it needs the WSGI factory (K-1/K-2).
- Adding a frontend job to CI. Valuable now that the bundle is not committed, but
  the workflow is already red (K-6) and that belongs to its own unit.
- Rewriting history to reclaim disk.

## Tasks

- [ ] T1 `.gitignore`: ignore `/static/`, stop ignoring `adminpro/package-lock.json`
- [ ] T2 `git rm -r --cached static/`, track the lockfile
- [ ] T3 `.dockerignore`: drop heavy/irrelevant paths from the build context
- [ ] T4 `Dockerfile`: multi-stage frontend build → Python runtime
- [ ] T5 `api/routes.py`: 503 with the build command when the bundle is missing
- [ ] T6 Docs: AGENTS.md, repo-map, runbook, known-issues, copilot pointer
- [ ] T7 Verify: bundle present → 200; bundle absent → 503; clean-clone tree

## Verification plan

| Check | Method | Expected |
| --- | --- | --- |
| `git status` after untracking | `git status --porcelain` | clean despite `static/` on disk |
| App still serves with a local build | Flask test client `GET /` | 200 |
| App fails usefully without a build | move `static/` aside, `GET /` | 503 + build command |
| Tracked tree lacks the bundle | `git ls-files static/` | empty |
| Lockfile is tracked | `git ls-files adminpro/package-lock.json` | present |
| Docs no longer claim the bundle is committed | grep for "committed build" | 0 stale claims |
| Dockerfile builds | `docker build` | ⛔ **unverifiable**: Docker daemon not running on this machine |

## Risk register

| Risk | Mitigation |
| --- | --- |
| `git rm --cached` also deletes the working tree | use `--cached` only; verified with `git status` and a live `GET /` |
| Fresh clone serves 404 with no clue | D4 returns 503 and prints the command |
| Image ships without the frontend | multi-stage `COPY --from=frontend /static ./static` |
| Lockfile turns out out of sync with `package.json` | verified earlier: 18 deps + 11 devDeps, zero drift, lockfileVersion 3 |
| Someone re-adds `static/` by accident | `/static/` anchored in `.gitignore` + a hard rule in `AGENTS.md` |
