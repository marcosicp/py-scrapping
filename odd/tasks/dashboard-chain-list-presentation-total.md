# Feature — Presentación column and per-list totals in the dashboard chain lists

Owner request (2026-11-07): in the four supermarket lists at the top of the
dashboard, add a **Presentación** column and, under each list, the **total** of
its items.

Branch: `feat/dashboard-chain-list-presentation-total` (base `main` `15d1790`).

## 1. What exists today

| Piece | File |
| --- | --- |
| Master grid (canonical rows) | `adminpro/src/app/pages/dashboard/dashboard.component.ts` |
| Four chain grids + header logos | `dashboard.component.html` |
| Chain-list selection (pure, id-keyed) | `adminpro/src/app/pages/dashboard/selection.ts` |
| Grouped payload (`unidad`, offers) | `api/services/matching.py` |

- `columnDefsGeneric` declares exactly two columns: `name` (Nombre) and `price`
  (Precio). There is no presentation column, and `ChainEntry` (`{id, name,
  price}`) has nothing to render.
- A legacy `totalRow(api, listaSuper)` in the component pushed
  `{name: 'Total', price: sum}` through `api.setPinnedBottomRowData(...)` after
  every toggle. It depends on each grid's API being captured by
  `onGridReady1..4`, and its actual rendering is **not verifiable without a
  browser**, so nobody in this repository has evidence that it ever showed.
  The owner asked for the total, which is the only evidence available.
- The master grid **already** has a Presentación column, `field: 'unidad'`.

## 2. Live data check (read-only, `lalistitadev.productos`, 2026-11-07)

Ran `group_products` over the 17 194 live documents:

- rows: **15 311**; rows with an empty `unidad`: **878 (5.7 %)** — so 94.3 % of
  rows can show a real presentation.
- every offer `price` is a `float` (14 129) or an `int` (3 023); **no** `null`,
  no string. Summing is safe; the price type in `ChainEntry` stays permissive
  only for legacy documents.
- the owner's filter row pair, with the new column's value:

  ```
  unidad='900 cc'  Aceite de girasol Cañuelas      carre 4399  disco 4700  mami 3269  hiper 4500
  unidad='1.5 lts' Aceite de girasol Cañuelas      carre 6985  disco 7450  mami 5299  hiper 7650
  ```

  SuperMami's offer name for both is `"ACEITE DE GIRASOL CAÑUELAS X ."` — it
  carries **no** size at all. A presentation read from the offer name is
  therefore impossible for that chain; it must come from the canonical row.

## 3. Decisions

- **D-14 — presentation comes from the canonical row, not the offer.** The
  chain entry carries the row's `unidad` (`data.unidad` in the master grid).
  Rationale: the live sample above, plus 1 121 (chain, offer-name) pairs that
  already collide across rows (see D-10) — the chain-local name is not a
  reliable carrier of the presentation, and for SuperMami it is absent.
- **D-15 — one total per list, computed from the list itself.** `chainTotal()`
  in `selection.ts` sums the numeric prices of the entries the grid actually
  shows. The legacy `totalRow()` / `setPinnedBottomRowData` path is **removed**:
  it produced the same number by a second route, it cannot be verified without a
  browser, and keeping both would render two totals for one list.
- **D-16 — the toggle and the total get an in-repo, browser-free test.**
  `adminpro/scripts/verify-selection.mjs` (run with `npm run verify:selection`)
  imports `selection.ts` directly through Node's type stripping. This closes the
  advisory `R3-SELECTION-TEST` left open by the native review of
  `review-cf61d65d3205f0ee`, whose harness lived in `/tmp`.
- **D-13 revised.** The previous round deliberately did not add a presentation
  column to the chain lists (scope A + B). The owner now asks for it, so D-13
  is superseded by D-14.
- Prices render through `Intl.NumberFormat('es-AR')` (`$3.374,60`). Amounts are
  kept as numbers in state so the total stays testable; only the rendering is
  formatted.

## 4. Tasks

- [x] T1 — `selection.ts`: `ChainEntry.presentation`, presentation argument on
      `toggleOffer`, `chainTotal()`, `formatAmount()`.
- [x] T2 — in-repo browser-free test `adminpro/scripts/verify-selection.mjs` +
      `npm run verify:selection`, RED before the implementation.
- [x] T3 — component/template wiring: Presentación column, total line under each
      of the four grids, legacy `totalRow()` and its four grid APIs removed.
- [x] T4 — verification and docs sync (`AGENTS.md` §8, `repo-map.md`,
      `runbook.md`).

## 5. Verification

Browser-free, per `AGENTS.md` §8 — the owner's round is the only UI evidence.

| Check | Result |
| --- | --- |
| `npm run verify:selection` (RED first) | **RED** `TypeError: list.some is not a function` — the old 4-argument `toggleOffer` received the presentation as its `selected` flag. **GREEN** `selection logic OK (19 checks)` |
| `npx tsc selection.ts --outDir /tmp/selcheck2 --module es2022 --target es2022 --strict --skipLibCheck` | exit 0 (`--skipLibCheck` required: ambient `@types/node` fails on `undici-types`) |
| `npm run build` | green, `7.872 s`, `main-FKTB7L7Y.js`; only the two pre-existing `Unable to locate stylesheet` warnings |
| shipped bundle | `Presentaci\xF3n` ×2 (master + chain grids), `Total: ` ×4 (one per chain list) |
| `pytest` | **405 passed, 9 skipped** — backend untouched |
| flake8 CI gate | 0 |

### Expected values for the owner's round (live replay, read-only)

Replaying the dashboard quick filter `aceite girasol cañu` over the live
`group_products` payload returns **5 rows** and these exact list totals:

| list | items | total |
| --- | --- | --- |
| Carrefour | 4 | `$15.783,00` |
| Disco | 2 | `$12.150,00` |
| SuperMami | 3 | `$26.068,00` |
| La Anónima | 2 | `$12.150,00` |

Per row (presentation · chain price):

```
'5 LT'    ACEITE DE GIRASOL CAÑUELAS X .                      mami 17500
'900 cc'  Aceite de girasol Cañuelas            carre 4399  disco 4700  mami 3269  hiper 4500
'1.5 lts' Aceite de girasol Cañuelas            carre 6985  disco 7450  mami 5299  hiper 7650
'187 cc'  Aceite en aerosol Cañuelas de girasol               carre 4399
''        Aceite mezcla Cañuelas girasol y oliva 15 l         carre 0
```

The last Carrefour line is a `price = 0.0` document (§6): it adds `$0,00` to
the Carrefour total, so the real deficiency is in the price, not in the sum.

### Owner's round (the only UI evidence this repository accepts)

1. `./dev.sh` or `python app.py`, open `/`, dashboard.
2. Filter `aceite girasol cañu`, tick the **5** rows until the search box is
   cleared (the chain lists stay populated after the filter is removed).
3. Each of the four lists shows **Nombre · Presentación · Precio**; the two
   Cañuelas oil rows read `900 cc` and `1.5 lts` while SuperMami's offer names
   stay identical — that difference is the whole point of D-14.
4. Under each list the total must match the table above.
5. Untick the `5 LT` row: SuperMami drops to 2 items and `$8.568,00`; the other
   three lists do not change.
6. Untick the `900 cc` row: Carrefour 3 · `$11.384,00`, Disco 1 · `$7.450,00`,
   SuperMami 2 · `$22.799,00`, La Anónima 1 · `$7.650,00`.

## 6. Commits and review

| commit | content |
| --- | --- |
| `e7bc60b` | `feat(ui)`: presentation + totals in the chain lists (`selection.ts`, component, template, in-repo check, npm script) |
| `1d0db76` | `docs(odd)`: this document + `AGENTS.md` §8, `repo-map.md`, `runbook.md` |

Native RDD review of the candidate (`15d1790..HEAD`, 9 files, 420 changed
lines, tier **medium**, lens `review-reliability`): lineage
**`review-2aebc6ac1cfea9fd`** — **approved**, then acknowledged and burned
(`gentle-ai.review-acknowledged/v1`). Delivery stays under ordinary repository
policy: nothing was pushed.

## 7. Follow-ups

- **Carrefour `price = 0.0`** (1 477 documents, scraper defect) now also
  understates the list totals; it is a separate task, not this one.
- The master grid's checkbox column keeps its inherited `data.selected` cosmetic
  desync (`seleccion-smart.md` §7).
