# Comparator focus — household basics, and a metric that says what pays

Branch: `feat/comparator-focus` (from `main@f60bfb4`).

## Goal

Stop growing the catalog and start measuring what the comparator actually
gains, so every later decision (category, chain, matching rule) is made on
evidence instead of volume.

## The owner decision this implements

- **Focus is `almacen` and household basics** — the things a household buys
  every week. `perfumeria` (higiene), `limpieza`, `bebidas`, `congelados`,
  `lacteos-y-frescos`, `carniceria`, `frutas-y-verduras` stay declared because
  they are part of that basket.
- **`mascotas` is dropped from every chain for now.** It is a peculiar
  category, it is not clear every chain carries it, and one chain's rendering
  already breaks the run. It can come back later as its own feature.

## The measurement problem this fixes

`python -m api.cli coverage` bins every row under the *single* category derived
from its members' majority. So a product that Carrefour files under
`desayuno-y-merienda` and Disco files under `almacen` — a real, correct
comparison — is counted under one of them and the other looks empty. The last
measurement therefore reported `desayuno-y-merienda` at 0.2 % and
`carniceria`/`lacteos`/`frutas`/`mascotas` at 0.0 % while comparable rows had
actually risen from 3 435 to 5 060.

A metric that hides real comparisons is worse than no metric: it points the
next month of work at the wrong category.

## Decisions

- **F-1 · `mascotas` leaves the declared categories of `supermami` and
  `laanonima`.** The leaf-n1 handling stays in the code and in its tests
  (it is correct, and it is the shape a category can have); only the
  declaration goes.
- **F-2 · A row knows every category its members carry, on request.**
  `group_products(docs, include_member_categories=True)` adds
  `row["categorias"]` (sorted, deduplicated, `[]` when none). Off by default so
  the API payload stays byte-identical — the SPA must not pay for a CLI
  instrument.
- **F-3 · Coverage counts a row under every category it contains.** No
  majority binning. "Rows of category X" means "rows that carry at least one
  document filed under X", and a cross-category comparison counts in both.
- **F-4 · Coverage also reports per chain.** The comparator's weakest link is
  a chain, not a category: a chain with no `ean` can only be joined by name.
  Counts per chain bucket, with the comparable share, answer "where does one
  more unit of effort buy the most comparisons".
- **F-5 · Volume is reported, never celebrated.** Every block prints documents,
  rows and comparable rows, so a category that adds 5 000 documents and ten
  comparisons is visibly a bad investment.

## Non-goals

- Touching the matching rule itself (this round only widens the measurement).
- Re-scraping anything: the numbers come from the catalog already stored.
- Fixing SuperMami's no-pagination page (its only trigger was `mascotas`, which
  is now out of scope; recorded as a follow-up).

## Tasks

### T1 · Drop `mascotas` from both scrapers

`supermami.categories` loses it; `laanonima.categories` and
`CATEGORY_NODES` lose it. The leaf handling, its tests and the laanonima module
docstring's leaf explanation stay — the docstring must stop naming `mascotas`
as the live example and describe the shape instead.

Acceptance: `/api/scrapers` and `python -m api.cli list` no longer show it; the
per-scraper identity tests pin the new tuples; `supermami` runs to completion
because the family that could not report a total is no longer declared.

### T2 · `group_products(include_member_categories=True)`

Per F-2. Default off, payload unchanged, row key order untouched when off.

### T3 · Coverage: per category without binning, plus per chain

Per F-3 and F-4, with the total line kept. Deterministic order (categories and
chains sorted), `(sin categoria)` last.

### T4 · Measure and record

Run the instrument against the local catalog and record the table in this
document: it is the map for the next round.

## Evidence

- Baseline before this round (local catalog, 39 041 documents): 31 535 rows,
  5 060 comparable (16.0 %), of which `almacen` 4 782 (28.8 %) — with the
  majority-binning artifact described above.
- **T4 — the map, measured on the local catalog after the fix**
  (`LALISTITA_ENV_FILE=.env.local python -m api.cli coverage`, 38 843 documents
  after the stale slice cleanup below):

  ```
  por categoria (una fila cuenta en cada categoria que porta):
  categoria           docs   rows2+chains       pct
  almacen            21520  16625   4783     28.8%
  desayuno-y-merienda 6804   6803   2263     33.3%
  lacteos-y-frescos    683    680     62      9.1%
  frutas-y-verduras    251    251     22      8.8%
  fresco              1413   1411     78      5.5%
  bebidas             2393   2304     85      3.7%
  congelados           314    313      9      2.9%
  perfumeria          3321   3221     89      2.8%
  limpieza            2059   2020     33      1.6%
  carniceria            85     84      0      0.0%
  total              38843  31337   5060     16.1%

  por cadena:
  cadena              docs   rows2+chains       pct
  carre              13018  13017   4448     34.2%
  disco               4800   4793   3209     67.0%
  mami                8835   8787   1036     11.8%
  hiper               8035   7998   1052     13.2%
  chang               4155   4154   2727     65.6%
  ```

- **What the map says.** The binning artifact was hiding most of the value:
  `desayuno-y-merienda` went from the reported 0.2 % to **33.3 %** (2 263
  comparisons that were being attributed to `almacen`), and it is now the second
  best category in the catalog. Categories that looked dead are simply small.
- **The real axis is the chain, and it is the EAN.** The three chains that
  publish a barcode join at 34 %, 66 % and 67 %; the two that do not
  (`mami` 11.8 %, `hiper` 13.2 %) join at a fifth of that. Together they carry
  18 000 of the 31 337 rows and produce 2 088 of the 5 060 comparable ones.
- **Volume versus comparison, per chain, measured**: La Anónima grew from 3 011
  to 8 233 documents this round and its comparable rows stayed at 1 052 (13.2 %).
  Adding products to a chain that cannot be joined puts nothing in front of the
  user.
- **Data hygiene**: dropping a declared category does not delete its stored
  slice. The 198 `mascotas` documents left in the local catalog by the earlier
  La Anónima run were deleted explicitly (local only); the same cleanup is
  needed in any database where that category was ever collected.
- **SuperMami now completes**: with `mascotas` undeclared, the no-pagination
  page shape that raised `the page reports no total` is never requested. The
  parser limitation is a recorded follow-up, not a live failure.

## Next round: where the effort buys the most

Ranked by comparable rows per unit of work, from the map above:

1. **Give `mami` and `hiper` an identity.** They are 18 000 rows and 2 088
   comparisons; the other three chains prove what a barcode is worth. First
   step is read-only: search both payloads for any barcode field we are not
   reading (Endeca `product.repositoryId`, JSON-LD `sku`/`gtin13`).
2. **Layer 2 for what stays without an EAN**: name tokens, presentation and
   brand already exist; measure which rule rejects the most near-misses.
3. **Categories last.** `desayuno-y-merienda` already joins at 33 %; the weak
   categories (`limpieza` 1.6 %, `perfumeria` 2.8 %) are weak because of the
   two no-EAN chains, not because of their size.
