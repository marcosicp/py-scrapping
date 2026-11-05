# Selección smart — canonical product rows with per-chain price columns

**Branch:** `feat/seleccion-smart` (from `main`)
**Status:** IN PROGRESS (T1-T5 pending)

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

- [ ] **T1 — VTEX EAN capture.** `api/scrapers/disco.py` and
  `api/scrapers/carrefour.py` read `items[0].ean` into a new `ean` document
  field (`""` when absent). Test-first: VTEX fixtures gain `ean`, the
  document-shape tests expect it (RED → GREEN). SuperMami, La Anónima and
  ChangoMás are NOT touched.
- [ ] **T2 — matching service.** New `api/services/matching.py`:
  normalization (name tokens, presentation per D-8, brand), layer-1 EAN
  grouping, layer-2 conservative canonical-key grouping, grouped output per
  §3. Test-first with synthetic fixtures covering: EAN exact match,
  token-set match across word order/stopwords, unit variants
  (`900 cc` ≡ `900 ml`, `1 kg` ≡ `1000 g`), unit-less bare number,
  brand rule (D-9), false-positive guards (different brand / different
  presentation / extra token ⇒ no match).
- [ ] **T3 — grouped endpoint.** `GET /api/productos/agrupados` in the
  products blueprint over the matching service; per-chain counts; error
  behavior mirroring the existing catalog endpoint. Test-first at the
  HTTP layer (same style as `tests/test_products_api.py`).
- [ ] **T4 — master grid.** The dashboard search view becomes the grouped
  grid: one row per canonical product, price column per chain; selection
  adds each present offer to its chain list (name+price of that offer),
  deselection removes them; the quick filter targets the master grid; the
  service calls `/api/productos/agrupados`. No persistence (D-7). Manual
  verification (`ng serve`/build + browser) — `adminpro` has zero specs.
- [ ] **T5 — docs sync.** `AGENTS.md` (§4 layout: matching service + new
  endpoint), `docs/agent-context/repo-map.md`, feature doc close-out with
  verification evidence.

## 5. Verification evidence

_To be filled as tasks close (observed outputs only)._

## 6. Out of scope

- ChangoMás in the grouped view (D-3).
- Shopping-list persistence (backend endpoint or localStorage).
- EAN capture for SuperMami / La Anónima (unprobed sources; layer 2 covers
  them).
- Re-scraping production data to backfill `ean` — happens on the next
  ordinary scrape run (owner's operation, D-4).
- Fuzzy/scored matching beyond the conservative rules (D-2).
