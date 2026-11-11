# Feature — Dashboard loading spinner tied to the catalog request

Owner request (2026-11-10): *"necesito que pongamos un spinner de carga. ahora hay
uno pero no funciona bien, es decir no espera a las llamadas del backend"*.

Branch: `feat/dashboard-loading-spinner` (base `main` `fe7e63d`).

## 1. What existed today

| Piece | File |
| --- | --- |
| Dashboard component | `adminpro/src/app/pages/dashboard/dashboard.component.ts` |
| Dashboard template | `adminpro/src/app/pages/dashboard/dashboard.component.html` |
| The only spinner in the app | `adminpro/src/index.html` (`.preloader`, "CARGANDO...") |
| Who dismisses that spinner | `adminpro/src/assets/js/custom.js:10` |
| Catalog request | `adminpro/src/app/service/app.service.ts` → `GET /api/productos/agrupados` |

Two facts explain the report:

1. The `.preloader` is the AdminPro template's **boot** cover. jQuery fades it out
   on DOM ready (`$(function () { $(".preloader").fadeOut(); })`), which happens
   when the bundle executes — long before the catalog request answers.
2. The dashboard had **no loading state of its own**. Content was gated by
   `*ngIf="items != undefined"`, so the whole fetch window rendered empty cards
   with no indication that data was on the way.

The subscription was also bare — `this.http.getExams().subscribe((a) => this.items = a)`
— with no error branch, so a failing backend produced no signal at all.

## 2. Decision

- One request, one flag. `loading` starts `true`, and `finalize` clears it on both
  outcomes, so the spinner lasts exactly as long as the fetch and a failure can
  never leave it spinning.
- The error branch sets `loadError` and renders a message plus a **Reintentar**
  button that re-runs `loadCatalog()`.
- Spinner CSS stays local to the component (`.spinner__wheel` + keyframes): the
  global `.loader` / `.loader__figure` in `assets/css/spinners.css` are
  `position: absolute` for the full-screen preloader and cannot sit inside a card.
- The `index.html` `.preloader` was deliberately **not** touched. It keeps
  covering the bundle-boot gap, and it cannot get stuck if bootstrap throws.
  Making it hand off to Angular was considered and rejected: it buys one
  continuous spinner at the cost of a forever-"CARGANDO..." page on a bootstrap
  error.

## 3. Verification (browser-free, per AGENTS.md §8)

- `cd adminpro && npm run build` → green, 6.4 s.
- Emitted bundle read back, since "which code shipped" is the only browser-free
  question that matters:
  - `static/main-*.js` contains the scoped rule
    `spinner__wheel[_ngcontent-%COMP%]{width:42px;height:42px;border:4px solid
    #e3e8ef;border-top-color:#1e88e5;border-radius:50%;animation:_ngcontent-%COMP%_spinner-rotate .9s linear infinite}`
    — the keyframes name is mangled consistently, so the animation is wired.
  - the label `CARGANDO PRODUCTOS...` is in the bundle.
- Build warnings `Unable to locate stylesheet: /assets/css/style.css` and
  `.../colors/default-dark.css` are **pre-existing** and not caused by this
  change; `static/assets/css/style.css` does exist, so the `<link href="./assets/...">`
  in `index.html` resolves at runtime.
- No automated assertion covers this: `adminpro` still has **zero `*.spec.ts`**,
  so there is no meaningful RED.

## 4. Owner's verdict

Owner's manual browser round (2026-11-10): *"quedó bien"* — the spinner appears,
waits for the backend and disappears with the data. This is the only UI evidence
this repository gets (AGENTS.md §8: agents do not open browsers here).

## 5. Native review — blocked by a false blocker

Recorded because it is a tool defect, not a code one.

- Lineage `review-e58728f2b1006399`, tier `medium`, one lens `review-reliability`,
  correction budget 49.
- The lens raised `R3-001` **BLOCKER**: *"this AdminPro code targets RxJS 6 where
  pipeable operators are provided by the dedicated operators entry point … the
  unresolved import breaks TypeScript compilation"*.
  **False**: `adminpro/package.json` pins `rxjs ~7.8.0` (7.8.2 installed) and
  `finalize` is exported from the root module — `node -e "require('rxjs').finalize"`
  → `function`, and `npm run build` is green.
- The provider refuter answered `inconclusive` with
  `proof: "probe unavailable on pi"` (same failure mode recorded in
  `odd/tasks/review-followups.md`), and native counted that as corroboration →
  `correction_required` with `fix_finding_ids: ["R3-001"]`.
- Bound STATUS then became permanently inconsistent: `authority.state:
  correction_required` while `next_transition` was `stop /
  corrupted_or_unverifiable_authority`, and a fresh `inspect` reported the same
  lineage as `fresh_target_ready`.
- Owner decision (2026-11-10): **leave the lineage in stop and continue**. No
  authority was mutated (no ABANDON, no RESET, no switch toggle). `R3-002`
  WARNING — no spec covers the loading/error/retry branches — is accepted as the
  known frontend-test debt, not fixed here.

Triage note for the next agent: a host-relayed capture leaves no readable result
in the tool output, but the finding text and the refuter's proof are in
`.git/gentle-ai/review-transactions/v2/<lineage>/review-state.json`
(`state.admitted_role_results`, `state.fix_finding_ids`).

## 6. Follow-ups

- Zero `*.spec.ts` in `adminpro` is what let `R3-001`-style claims about this
  codebase stand and what leaves the loading/error/retry branches unasserted.
- `custom.js` fades the boot preloader on DOM ready. If the owner wants one
  continuous spinner instead of two, the handoff belongs in `AppComponent` plus a
  removal of that fadeOut line — with an explicit bootstrap-failure fallback.
