# Feature: Angular 21 change detection regression

STATUS: DONE
Diagnosed: 2026-11-04, from the owner's report "no estoy viendo la información
en la vista /#/dashboard".

## Symptom

`/#/dashboard` renders its layout (header, four cards, the hint text) but the
data never appears: no supermarket counters, no grids, no rows. The API answers
`/supermercados` 200 with 2792 documents.

## Evidence (measured, not inferred)

| Probe | Result |
| --- | --- |
| `GET /supermercados` from the page | 200, 919690 bytes, 2792 `todos` |
| The app's own XHR | one request, `status 200`, no network error |
| `JSON.parse` of the payload | observed, 919690 chars |
| `window` errors / unhandled rejections / console output | none |
| zone.js | loaded; `XMLHttpRequest.prototype` carries `__zone_symbol__open`/`__zone_symbol__send` |
| Trusted click on a neutral area | DOM unchanged |
| Dev mode (`ng serve`, `ng.getComponent`) | `component.items` **is** set: keys `carre/disco/hiper/mami/todos`, `todos.length = 2792` |
| `ng.applyChanges(component)` | 4 badges appear (`0/0/2792/0`), 5 `ag-grid-angular`, 24 rows |

Conclusion: the HTTP layer, the subscription, the template and the bindings are
all correct. **No change-detection cycle is ever scheduled after the async
response**, so the view keeps its bootstrap render.

## Root cause

The app is a legacy `NgModule` bootstrapped with
`platformBrowserDynamic().bootstrapModule(AppModule)` (`adminpro/src/main.ts`).
On Angular 21 that no longer implies zone-driven change detection: zone-based
CD has to be provided explicitly with `provideZoneChangeDetection()`. Without
it, `this.items = a` inside a `subscribe` callback updates the component and
never schedules a render, and every other async-driven update in the app
(login, progress) is in the same state.

Introduced by the Angular 19 → 20 → 21 migration: the app kept bootstrapping
the old way and nothing in the suite noticed, because there are zero
`*.spec.ts` files.

## Second defect found while verifying

`DashboardComponent.addItemToList` switches on the literal `supermercado`
value (`'SuperMami' | 'Disco' | 'Carrefour' | 'Hiperlibertad'`). The database now
stores `La Anónima` (see `odd/tasks/scrape-admin-view.md`), so selecting a
product from the only chain with data hit `default: break`: the comparison
panels silently ignored it.

## Tasks

- [x] **T1 — Restore zone-based change detection.** `provideZoneChangeDetection
  ({ eventCoalescing: true })` in `AppModule.providers`, next to the existing
  `HashLocationStrategy` and `provideHttpClient` providers.
- [x] **T2 — Teach the dashboard the current chain name.** `case 'La Anónima'`
  feeding the third comparison panel, keeping the legacy `'Hiperlibertad'` case
  for documents stored under the old name.
- [x] **T3 — Rebuild and verify** the bundle that `/` serves (`npm run build`
  writes into `static/`) and re-check both the built page and `ng serve`.

## Verification observed

| Check | Result |
| --- | --- |
| `npm run build` | clean build, `static/` regenerated |
| Built page `/#/dashboard` on :3000 | 4 counters render (`carre 0`, `disco 0`, `hiper 2792`, `mami 0`), 5 grids, 24 rows on first paint |
| `ng serve` :4200 | same, without forcing anything |
| Console | no errors or warnings |
| Selecting a row | it lands in the La Anónima comparison panel with its total |

## Why no test

`adminpro` has karma + jasmine configured and **zero spec files**; there is no
existing harness to extend and adding one is its own work unit. Verification is
the build plus the browser observation above. Making this kind of regression
catchable needs a real frontend test setup, recorded as a follow-up.

## Follow-ups

- The third comparison panel still shows the HiperLibertad logo
  (`assets/images/libertad-logo.png`) above La Anónima's count. Replacing it
  needs a brand asset decision, so it was left untouched.
- `provideZoneChangeDetection` restores the pre-migration behavior. Moving the
  app to zoneless-correct signals is a broader refactor of every component.
- A frontend test harness (or at least one smoke spec) would have caught this.
