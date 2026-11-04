# Feature: angular-21-migration

| Field | Value |
| --- | --- |
| Status | in progress |
| Owner | el Gentleman (parent orchestrator) |
| Branch | `main` (owner commits to main locally) |
| Created | 2026-11-03 |

## Problem

`adminpro/` is on Angular 19.2.19. Four production advisories
(`@angular/common`, `@angular/compiler`, `@angular/core`, `@angular/router`)
declare vulnerable ranges `<=19.2.25`, so **19.x has no patch** — the last
published 19.x is 19.2.25, still inside the vulnerable range. Only a newer major
closes them.

Nobody has captured the 71 devDependency advisories yet either; they are a
separate concern (Phase C of `dependency-vulnerability-remediation`).

## Correction to an earlier claim

The audit document said these were fixed only in Angular 22, because that is what
`npm audit` reports as `fixAvailable`. That was misleading: npm reports the
nearest version that clears the **entire** tree, including devkit packages. The
advisory ranges themselves are `<=19.2.25`, so **Angular 20 and 21 already sit
outside them**. The owner's instinct to stop at 21 is correct and cheaper.

## Verified compatibility (before touching anything)

| Constraint | Required by | Current | Verdict |
| --- | --- | --- | --- |
| Node | `@angular/cli@21` → `^20.19 \|\| ^22.12 \|\| >=24` | 26.x | ✅ satisfies `>=24` |
| TypeScript | `@angular/compiler-cli@21` → `>=5.9 <6.0` | `~5.8.3` | ⛔ bump in the 21 step |
| zone.js | `@angular/core@21` → `~0.15.0 \|\| ~0.16.0` | `~0.15.1` | ✅ |
| `@angular/material@21` | needs `@angular/cdk@21` | 19.2.19 pair | ⛔ bump together |
| **ag-grid** | `ag-grid-angular@32.3.9` → `@angular/core >= 16` | 32.3.9 | ✅ **no migration needed** |

The ag-grid finding removes the largest anticipated risk. Its latest major (36.x)
would require rewriting grid API calls; it is not needed.

## Strategy — one major at a time

Two majors, two commits, a build between them. Going straight to 21 would merge
two sets of breaking changes into one unverifiable step.

1. **20** — `ng update` for core, cli, cdk, material. TypeScript stays 5.8.
2. **21** — same set plus TypeScript 5.9.

`ng build` writes into the committed `static/` (`angular.json:16`), so each step
ends with a rebuilt bundle in the same commit as the source change.

## Non-goals

- ag-grid migration (not required — see table above).
- Removing karma/jasmine (Phase C, separate).
- Migrating NgModule-based components to standalone. The workspace sets
  `standalone: false` deliberately; the migration keeps it.
- Fixing the hardcoded API base URL (K-8/T-7 family).

## Tasks

- [x] T1 `npm install` baseline and confirm the current tree builds (19.2.22, 9s)
- [x] T2 Create the feature document and mirror in Engram
- [x] T3 Angular 19 → 20 (core, cli, cdk, material), build OK
- [x] T4 `npm audit --omit=dev` after 20: **0 vulnerabilities**
- [x] T5 Angular 20 → 21 + TypeScript 5.9.3 — required a tsconfig fix
- [x] T6 Rebuild `static/` from Angular 21 and commit as one work unit
- [x] T7 Verify the four production advisories are gone — confirmed
- [x] T8 Update `AGENTS.md` / `repo-map.md` / `runbook.md` to 21.x

## Decisions

- **D1 — Two steps, not one.** 19 → 20 → 21, verifying a real build at each
  step. A single 19 → 21 jump cannot separate "20 broke it" from "21 broke it".
- **D2 — Keep NgModule.** The workspace is intentionally `standalone: false`.
  Converting to standalone is a behavioural refactor and does not belong inside a
  security-driven major upgrade.
- **D3 — `static/` is rebuilt and committed with the source change.** It is
  committed build output by this project's convention; leaving it stale would
  mean the served app is older than the source it claims to be.
- **D4 — No ag-grid bump.** Verified unnecessary.

## Verification plan

| Check | Method | Expected |
| --- | --- | --- |
| Dependency tree resolves | `npm install` exit code | 0, no peer errors |
| App compiles | `npx ng build` | success, output in `static/` |
| Production advisories closed | `npm audit --omit=dev` | 0 |
| Served bundle is the new build | compare `static/index.html` script hash to fresh build | matches |
| Nothing silently dropped | `git status static/` | only expected hash churn |

## Risk register

| Risk | Mitigation |
| --- | --- |
| `ng update` rewrites more than expected | review the diff per step; commit only after a build |
| Global `ng` is 14.x and cannot run this workspace | always `npx ng` from `adminpro/` |
| Rebuilding adds orphaned hashed files | inspect `git status static/` and delete leftovers explicitly |
| Peer conflict from `bootstrap`/`jquery`/`popper.js` | these are plain scripts, not Angular peers; expect no issue |

## Outcome

| Check | Result |
| --- | --- |
| `npm install` (19 baseline) | clean |
| `npx ng build` on 19.2.22 | success, 9s |
| `npx ng build` on 20.3.42 | success, 12.6s |
| `npx ng build` on 21.2.29 | success after the tsconfig fix, 8.3s |
| `npm audit --omit=dev` | **0 vulnerabilities** |
| `npm audit` (full) | 75 → 36, **0 critical**, all dev tooling |
| Flask serves the new bundle | `main-VSNNK3WP.js`, all referenced files exist |
| Old hashes removed | yes, only the four new files remain |

### What actually broke, and why it is worth remembering

`ng update` never ran. It tried to resolve `20.3.35` next to `21.2.26` and aborted
on incompatible peers. Pinning the whole `@angular/*` set explicitly was
deterministic and produced a reviewable diff instead of a resolver negotiation.

The one real source change was `tsconfig.json`: `"moduleResolution": "node"`
(Node10) ignores package `exports` maps, and `@angular/common@21` stopped shipping
a physical `http/` directory. The build failed with `TS2307: Cannot find module
'@angular/common/http'`. Fixed with `"bundler"` + `"module": "preserve"`, and
recorded as trap T-11 in `AGENTS.md` so nobody reverts it.

`ag-grid` was not touched, as predicted: `ag-grid-angular@32.3.9` peers
`@angular/core >= 16`.

### Post-migration regression (found 2026-11-04, fixed)

After the v21 migration the app rendered static content only: every async update
(an `HttpClient` response in `/#/dashboard`, for instance) was invisible, with
no console error, because `platformBrowserDynamic` no longer implies zone-driven
change detection on Angular 21. Fixed with `provideZoneChangeDetection({ eventCoalescing: true })`
in `AppModule.providers` — see `odd/tasks/angular-21-change-detection.md` and
trap **T-11** in `AGENTS.md`. It went unnoticed because `adminpro` has no specs.

### Open follow-ups (not done here)

- `adminpro/package-lock.json` is **gitignored**, so installs are not
  reproducible and CI cannot detect drift. Worth tracking it in a separate unit.
- `static/prerendered-routes.json` is emitted by the builder and swallowed by the
  `*.json` gitignore rule. Harmless, but it is the documented trap in the wild.
- Build warns `Unable to locate stylesheet: /assets/css/style.css` and
  `/assets/css/colors/default-dark.css` — pre-existing, unrelated, and both files
  do exist under `src/assets/`; the warning comes from the absolute path used in
  `src/index.html`.
