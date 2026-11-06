# Selección smart — canonical product rows with per-chain price columns

**Branch:** `feat/seleccion-smart` (from `main`)
**Status:** T1-T5 DONE. Merged to local `main`. One advisory follow-up is tracked in §7.

## Review

- T1 (`78078bc`): lineage `review-780de32cfa49dba5` (medium, 1 lens
  `review-reliability`, 5 files / 262 lines) — START created, first capture
  forecasted (1 model run, `pi_host_relay`) and acknowledged, but the relay
  failed three times with a transient **429 overloaded** from the model
  server (no mutation performed). The lineage stays open in `reviewing`;
  resume with a bound STATUS and resubmit the exact reoffered binding.
  Retried after T2: the relay still returns 429 (4 attempts). T2 (`e0b75c0`)
  and T3 (`b3f60c5`) reviews are not started yet — they queue behind the
  same server saturation; start them once the relay recovers.
- Docs candidate (`AGENTS.md` + `docs/agent-context/runbook.md` + this doc):
  lineage `review-655736f638cb11c2` (medium, 1 lens `review-reliability`, 3
  files / 101 lines) — **approved**, authority burned
  (`gentle-ai.review-acknowledged/v1`).
- Whole backlog (`base-diff add44ca..HEAD`, 22 files / 2 985 lines): lineage
  `review-bd0ee6c2631c75d1` — reviewer + refuter produced two **deterministic,
  introduced** findings (R3-001 BLOCKER: unguarded multi-chain selection;
  R3-002 CRITICAL: SuperMami operator messages). Correction plan of 74 diff
  lines accepted; both fixed in `00ce0dc` and `9637b43`. The corrected
  candidate required `review recover` with `disposition=scope_changed`
  (the correction added `api/scrapers/base.py` to the scope).
- `review-3368f50769e37912` (successor, 22 files / 3 021 lines) — **approved**,
  authority burned. Two advisory WARNINGs, informational, no correction
  offered: `api/services/matching.py:162-165`, `api/scrapers/supermami.py:162-169`.

Today a search like "aceite girasol natura 900" returns one loose row per
supermarket and the user adds each one individually. This feature shows a
single canonical product row with one price column per supermarket; selecting
it adds the product to every supermarket list where it exists, each with its
own price, so the user can compare the per-chain list totals.

Requested by the owner: *"cuando busca por ejemplo 'aceite girasol natura 900'
le aparezca un solo item y columnas con los precios de cada supermercado. Y que
al seleccionar el item vaya automaticamente a la lista del supermercado que le
corresponda con su respectivo precio."*

---

## 1. What exists today (investigation evidence)

**No shared identifier is persisted.** Each chain's `sku` is a chain-local id
(VTEX `productId` in Disco/Carrefour, Endeca `item_id` in SuperMami, La
Anónima `art_<id>`); ChangoMás has none. A grep for `ean|gtin|barcode|upc`
over `api/` returns zero hits.

**Live probe (this session, public VTEX catalog API):** Disco and Carrefour
DO expose `items[].ean` (real EAN-13) plus `measurementUnit`/`unitMultiplier`.
Example: "Aceite de girasol Natura 900 cc" → Carrefour `ean=7790272001005`,
Disco `ean=7790272001036` (same search, different variant EANs — EAN gives an
exact match only when the same variant exists in both chains). The current
VTEX scrapers do NOT read `ean` (`api/scrapers/disco.py:459-468`,
`api/scrapers/carrefour.py:233-242`).

**Zero cross-supermarket matching today.** `ProductService.catalog()` buckets
by `supermercado` substring and dedupes by exact name within the bucket only
(`api/services/products.py:26-56`). No fuzzy/normalized matching anywhere.

**Normalization base exists.** `name_parse()` splits name/unidad
(`api/helpers.py:12-34`); 4 of 5 scrapers store `brand` (La Anónima stores
`""`).

**Frontend.** Four in-memory arrays × four ag-grids, exact-name toggle, zero
persistence (`dashboard.component.ts:17-20,184-218`); search is a client-side
ag-grid quick filter over `items.todos`.

**Volume.** `todos` ≈ 15.8k docs; the catalog is already read whole into
memory (`api/repositories/products.py:51-58`), so deterministic-key grouping
is query-time viable; pairwise fuzzy matching is not.

## 2. Decisions

**D-1 — Selection adds the product to every list where it exists.** Selecting
the canonical row adds the product to the list of EACH supermarket carrying
it, with that chain's price; if absent in a chain, it is simply not added
there. (Owner decision.) The point is comparing per-chain totals.

**D-2 — Conservative grouping.** Layer 1: exact EAN match (only where `ean`
is captured). Layer 2: strict canonical key (below). Anything doubtful stays
loose — a false positive corrupts the price comparison, a false negative
keeps today's behavior (fail-open). (Owner decision.)

**D-3 — ChangoMás is out of scope** (persisted but not shown in the UI,
K-12; poorest data: raw names, no brand/unidad).

**D-4 — EAN capture is VTEX-only.** Disco and Carrefour scrapers read
`items[0].ean` (verified live). SuperMami (Endeca) and La Anónima (JSON-LD)
were not probed and rely on layer 2. Missing EAN is stored as `""` (same
convention as La Anónima's empty `brand`). `replace_products` repopulates the
field on the next scrape — no migration; old docs without `ean` simply fall
to layer 2 until re-scraped.

**D-5 — Query-time deterministic matching.** No new dependencies:
normalization uses stdlib `unicodedata` (NFKD, strip combining marks). No
pairwise fuzzy matching.

**D-6 — New endpoint, old contract untouched.** `GET /api/productos/agrupados`
serves the grouped payload; `/supermercados` keeps its exact contract
(pinned by `tests/test_products_api.py`).

**D-7 — No list persistence** (status quo). The master grid is a new search
view; the four per-chain lists keep working as today.

**D-8 — Presentation normalization.** Quantity + base unit: `kg→1000 g`,
`l/lt/lts→1000 ml`, `cc≡ml`. A bare numeric token in the name ("Natura 900",
where `name_parse` finds no unit) counts as a unit-less presentation.
Presentation match = equal quantity AND (equal unit OR unit missing on one
side).

**D-9 — Brand rule.** If both sides carry a brand, the normalized brands must
be equal. If one side lacks a brand (La Anónima), the match requires equal
name token-set AND presentation.

## 3. Contract the implementation must satisfy

**Canonical key (layer 2):** name → lowercase, strip accents, collapse
whitespace, drop punctuation; token-set excluding Spanish stopwords
(`de/del/la/el/con/sin/en/x/...`), sorted. Match requires: equal token-set,
presentation per D-8, brand per D-9. Layer 1 (EAN) wins on conflict; a
document belongs to exactly one group.

**Grouped payload (`GET /api/productos/agrupados`):**

```
{"productos": [
  {"id": "<stable id: sha1 of winning key>",
   "name": "<display name>", "unidad": "<as scraped>", "brand": "<brand>",
   "offers": {"carre": {"name": ..., "price": ...},
              "disco": {...}, "mami": {...}, "hiper": {...}},
   "match": "ean" | "key" | "solo"},
  ...],
 "carre": n, "disco": n, "mami": n, "hiper": n}
```

Unmatched products are included with a single offer (`match: "solo"`) — the
user must still be able to add products carried by one chain only. The chain
keys mirror the ones Angular already reads (`carre/disco/mami/hiper`).
Deterministic ordering: by display name, then stable id. Display name = name
of the offer with the most information (brand+unidad present), tie-broken by
bucket order `carre → disco → mami → hiper` (mirrors the existing catalog
tie-break convention).

## 4. Tasks

- [x] **T1 — VTEX EAN capture.** DONE in `78078bc` (evidence §5). `api/scrapers/disco.py` and
  `api/scrapers/carrefour.py` read `items[0].ean` into a new `ean` document
  field (`""` when absent). Test-first: VTEX fixtures gain `ean`, the
  document-shape tests expect it (RED → GREEN). SuperMami, La Anónima and
  ChangoMás are NOT touched.
- [x] **T2 — matching service.** DONE in `e0b75c0` (evidence §5). New `api/services/matching.py`:
  normalization (name tokens, presentation per D-8, brand), layer-1 EAN
  grouping, layer-2 conservative canonical-key grouping, grouped output per
  §3. Test-first with synthetic fixtures covering: EAN exact match,
  token-set match across word order/stopwords, unit variants
  (`900 cc` ≡ `900 ml`, `1 kg` ≡ `1000 g`), unit-less bare number,
  brand rule (D-9), false-positive guards (different brand / different
  presentation / extra token ⇒ no match).
- [x] **T3 — grouped endpoint.** DONE in `b3f60c5` (evidence §5). `GET /api/productos/agrupados` in the
  products blueprint over the matching service; per-chain counts; error
  behavior mirroring the existing catalog endpoint. Test-first at the
  HTTP layer (same style as `tests/test_products_api.py`).
- [x] **T4 — master grid.** DONE in `6b97d82` `feat(ui): grouped master grid
  with per-chain price columns` (3 files, +62/−52; evidence §5). Its open
  defect was closed by the review correction `00ce0dc` (evidence §5). The dashboard search view becomes the grouped
  grid: one row per canonical product, price column per chain; selection
  adds each present offer to its chain list (name+price of that offer),
  deselection removes them; the quick filter targets the master grid; the
  service calls `/api/productos/agrupados`. No persistence (D-7). Manual
  verification (`ng serve`/build + browser) — `adminpro` has zero specs.
- [x] **T5 — docs sync.** DONE: `AGENTS.md` (§4 layout: matching service, the
  grouped endpoint, dashboard master grid; §8 suite count 396),
  `docs/agent-context/repo-map.md` (service/blueprint rows plus the
  `/api/productos/agrupados` contract) and the runbook route count (19).

## 5. Verification evidence

**R3-001 fix — `00ce0dc` `fix(ui): never dereference an undefined chain list
when selecting a row`** — `addRemoveOffer` defaults a missing list to `[]` and
`totalRow` only calls `setPinnedBottomRowData` when the API exposes it, so no
chain branch can throw mid-selection (the observed shape of the defect: only
the Carrefour list received the item). Build green; the runtime confirmation
is the browser round described in §6. **The original defect record, kept as
history:** selecting the four-offer `Aceite de girasol Natura 900 cc` row added
the item only to the Carrefour list while `window.onerror` stayed empty, and
`addItemToList` branched carre→disco→mami→hiper.

**R3-002 fix — `9637b43` `fix(scrapers): restore SuperMami's operator-visible
save and total messages`** — `ScrapeContext.save` gained an optional `scope`
that overrides only the message; the persisted slice still comes from
`categoria`/`subcategoria`, so documents keep their `categoria` field and
`replace_products` keeps the same slice. SuperMami passes `scope=self.label`
and closes with `PROCESO TERMINADO CON <n> productos`. Rejected alternative:
dropping `categoria=` restored the message but removed `categoria` from the
stored documents (10 tests failed on the document shape). Verification: pytest
**396 passed / 9 skipped**, flake8 gate **0**.

**T4 — `6b97d82`** — `npm run build` green (9.8 s on re-run, two pre-existing
stylesheet warnings for `/assets/css/style.css` and `default-dark.css`).
Re-running the build on the branch head reproduced the **same chunk hash**
`main-SW2CI6UX.js` as the bundle already served by Flask, so `/` on :3000 was
serving HEAD, not a stale build. Live payload check:
`GET /api/productos/agrupados` → 200, 5 063 545 bytes, `carre=6187,
disco=4704, hiper=3011, mami=3210`.

**T2 — `e0b75c0` `feat(services): add cross-supermarket matching service`**
— new `api/services/matching.py` (320 lines, pure function, stdlib only):
layer-1 EAN groups, layer-2 strict canonical key + D-2 ambiguity guard
(loose groups join exactly one strict group or stay solo; loose↔loose
never merges). RED: `ModuleNotFoundError`. GREEN: 21 new tests (EAN exact,
word order/stopwords, `900 cc`≡`900 ml`, `1 kg`≡`1000 g`, bare number,
brand rule, all false-positive guards, ambiguity guard, solo rows,
deterministic order); full suite **391 passed / 9 skipped**; flake8 gate
**0**. Parent read the whole module before commit. Worker judgment calls
recorded in the doc: `match` is `ean`/`key` only for ≥2-member groups
(singleton with EAN is `solo` but keeps the EAN-stable id); docs without
any presentation only group with each other; pack quantities (`X2`) and
unknown units are not parsed; per-chain duplicate offers: first wins.

**T3 — `b3f60c5` `feat(api): expose the grouped catalog at
/api/productos/agrupados`** — `ProductService.grouped_catalog()` (same
repository port as `catalog()`) + blueprint route mirroring the
`/supermercados` two-branch error fallback, adapted to
`productos`/counts. RED: 5 failed (404). GREEN: 5 new HTTP tests (§3
shape, EAN + key + solo in one payload, both error branches, empty repo);
full suite **396 passed / 9 skipped**; flake8 gate **0**.

**T1 — `78078bc` `feat(scrapers): capture EAN from VTEX items in Disco and
Carrefour`** — RED: `pytest tests/test_scraper_disco.py
tests/test_scraper_carrefour.py` → 4 failed, 45 passed (missing `ean`).
GREEN: both files 49 passed; full suite **370 passed / 9 skipped**; flake8 CI
gate **0**; hygiene grep clean. Parent spot check re-ran both files
(49 passed) and the gate (0) on the committed diff.

## 6. Out of scope

- ChangoMás in the grouped view (D-3).
- Shopping-list persistence (backend endpoint or localStorage).
- EAN capture for SuperMami / La Anónima (unprobed sources; layer 2 covers
  them).
- Re-scraping production data to backfill `ean` — happens on the next
  ordinary scrape run (owner's operation, D-4).
- Fuzzy/scored matching beyond the conservative rules (D-2).

## 7. Follow-ups

- **Advisory WARNINGs from the approved review** (`review-3368f50769e37912`),
  informational, no correction was offered for them:
  `api/services/matching.py:162-165` and `api/scrapers/supermami.py:162-169`.
  The provider did not expose the claim text in the closure, so read those
  lines before acting on them.
- **Cosmetic, pre-existing:** `cellRender.ts` toggles `data.selected` and calls
  `addItemToList`, so a checkbox can visually desync from `data.selected` until
  the grid refreshes.
- **Confirmation round:** the fixed selection path was verified by tests and a
  build, not yet by a browser round; one hypothesis-driven round per
  `AGENTS.md` §8 is still due.
