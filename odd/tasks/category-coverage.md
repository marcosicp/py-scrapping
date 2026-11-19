# Category coverage — first-class category dimension on the read path

Feature branch: `feat/category-dimension` (from `main@535d1e1`).

## Goal

Make the supermarket catalog grow beyond `almacen` **without breaking the
dashboard**, and make "how many chains carry this product" a number we can
read instead of guess.

The owner's framing: *the scraped items should be present in all or most of
the chains we already scrape, so prices can actually be compared.* That
reframes the work: more categories is not the objective, **comparable**
categories is.

## Measured baseline (read-only, 2026-11-21)

Catalog size from the VTEX `resources` header and the SuperMami/La Anónima
menus; stored size from MongoDB **read through `load_dotenv('.env')`, the same
configuration `app.py` uses** (the local `mongod` has no `ean` and no
ChangoMás, and measuring against it once produced a wrong coverage figure in
this very document).

| Chain | Declared categories | Stored docs |
| --- | --- | --- |
| Carrefour | `almacen`, `desayuno-y-merienda` | 6 187 |
| ChangoMás | `almacen` | 4 099 |
| Disco | `almacen` | 4 720 |
| SuperMami | `almacen` | 3 251 |
| La Anónima | `almacen` | 3 036 |
| **Total** | | **21 293** (15 000 with `ean`) |

`/api/productos/agrupados` today: **21 293 docs → 16 588 rows → 3.77 MB**, and
of those rows **13 584 (81.9 %) carry a single chain**; 3 004 (18.1 %) carry two
or more — 1 852 with two, 756 with three, 292 with four and **104 rows with all
five chains**.

Two consequences decide the order of this document:

1. Adding the "góndola" wave (~200 000 docs) at today's read path multiplies
   this by roughly 14 → a ~50 MB payload with ~230 000 client-side ag-grid
   rows. That is a broken app, not a bigger one.
2. `categoria` is written by every scraper but **read by nothing**: the
   repository uses it only as the `replace_products` slice key. The API and the
   SPA cannot filter, count or navigate by it.

## Decisions

- **C-1 · Read path first.** No chain gets a new category until the API can
  filter by category and report the category list. This document covers that
  read path only; the chain expansions are separate feature documents.
- **C-2 · The filter applies to grouped rows, not to documents.** A row that
  has offers from two chains must keep all of them when the user filters; the
  database-level filter would drop the offers whose slug differs.
- **C-3 · A row's `categoria` is derived from its member documents**: the most
  frequent non-empty `categoria` value, ties broken alphabetically, `None` when
  no member carries one. This is deliberately **not** a canonical vocabulary
  yet — the site slugs still disagree across chains (`perfumeria` vs
  `perfumeria-y-farmacia` vs `perfumeria-y-belleza`), and inventing the mapping
  before we have data from more than one category would freeze a guess.
- **C-4 · `categorias` is the sorted list of distinct non-empty slugs** in the
  catalog, present in the happy payload **and** in both legacy error fallbacks
  so the SPA never has to guard for its absence.
- **C-5 · A category value is never an error.** An unknown non-empty slug
  yields an empty `productos` list plus the full `categorias`, matching the
  blueprint's existing "answer 200 with a usable payload" convention. An empty
  value (`?categoria=`) behaves exactly like an absent one: it is the URL of a
  client that always appends the parameter, so answering it with an empty
  catalog would hide the dataset, while no-filter is the documented baseline.
- **C-6 · Payload changes are additive only.** `productos`, the five bucket
  counts and the `error` key keep their current shape and names (D-7 legacy
  parity): the Angular client must keep working against an old API and an old
  client must keep working against the new API.
- **C-7 · Coverage is measured offline, not per request.** Grouping the whole
  catalog per request is already the read path's cost; computing per-category
  coverage inside the request would double it. The metric lives in a CLI
  subcommand run after each chain expansion.

## Non-goals

- Canonical category vocabulary and its per-chain mapping (C-3 defers it).
- Server-side pagination of `productos` (the filter is the lever this round).
- Any scraper category declaration: chains are separate documents, sequenced
  SuperMami + La Anónima → Carrefour + ChangoMás → Disco (Disco last: the
  `fq=P:` price filter stores 105 of 683 products in `almacen/harinas` and 369
  of 2 372 in `almacen/snacks`, so it must be decided before it is multiplied
  by eleven categories).
- Frescos (carnes, frutas y verduras, panadería al peso): blocked on
  price-per-kg modelling.

## Tasks

### T1 · Repository: filter by category and list the categories — DONE

`ProductRepository` gains `find_all(categoria: str | None = None)` and
`categories() -> list[str]`. The Mongo adapter filters on the stored field and
uses `distinct` for the list; both fakes implement the same contract.

Acceptance: a filtered read returns only that slice and the unfiltered read is
byte-identical to today; `categories()` is sorted, string-only, deduplicated.

### T2 · matching: every row knows its category — DONE

`_row()` adds `categoria` per C-3. Purely additive to the row dict.

Acceptance: a row with mixed member slugs takes the majority; a tie breaks
alphabetically; a row with no categorized member has `categoria: None`; every
existing row key and value is unchanged.

### T3 · Service and blueprint: `?categoria=` and `categorias` — DONE

`ProductService.grouped_catalog(categoria=None)` filters the grouped rows (C-2)
and adds `categorias` (C-4); `/api/productos/agrupados` reads the query string;
both error fallbacks gain `"categorias": []`.

Acceptance: no query string behaves exactly as today plus `categorias`; a known
slug returns only that category's rows; an unknown slug returns an empty
`productos` with the full `categorias`; the five bucket counts stay computed
over the whole catalog in every case.

### T4 · CLI: `coverage` subcommand — DONE

`python -m api.cli coverage` prints, per category: documents, rows, rows with
two or more chains, and the resulting percentage; plus a total line. Read-only.

Acceptance: no network, no writes; grouping is delegated to the same services
the API uses, so the number cannot drift from what the dashboard shows.

### T5 · SPA: category selector — DONE

A native `<select>` in the dashboard (no new Angular Material modules) bound to
`categorias`, with an "all" option, re-fetching `/api/productos/agrupados` with
the selected slug. The default selection stays "all" so first paint matches
today's behaviour.

Acceptance: `npm run build` succeeds and `npm run verify:selection` stays green.
Browser verification belongs to the owner: agents do not open browsers in this
repository (AGENTS.md §8).

## Evidence

- Cost model per chain, VTEX 2 550 window ceiling and the Disco `fq=P:` gap are
  recorded above from live read-only probes; the full per-category catalog table
  lives in the analysis that opened this feature (session 2026-11-21).
- **T4 baseline on the deployed database** (`python -m api.cli coverage`, which
  now loads `.env` exactly like `app.py` and prints the resolved source):

  ```
  source: lalistitadev @ cluster0.fosxvtw.mongodb.net
  categoria           docs   rows2+chains       pct
  almacen            21293  16588   3004     18.1%
  total              21293  16588   3004     18.1%
  ```

  Two independent measurements agree (this CLI and a direct `find`+`pymongo`
  probe), and the earlier 6.7 % figure is retired: it came from the local
  `mongod`, which carries no `ean`.
- **Whole suite**: 520 passed, 16 skipped (opt-in MongoDB integration tests),
  flake8 CI gate 0. The seven new opt-in cases come from giving the new
  repository contract tests the same real-Mongo variant every other repository
  test has; `AGENTS.md` §8 and `docs/agent-context/runbook.md` moved from nine
  to sixteen skips.
- **C-5 in practice**: an unknown slug answers an empty `productos` with the
  full `categorias`; an empty value behaves like no parameter.
- **Native review** (`review-bb299de768e979df`, tier medium, ONE lens
  `review-reliability`): the reviewer found **R3-001 (CRITICAL, deterministic,
  introduced)**: the code filters only on a truthy slug while C-5 said an empty
  value must yield an empty `productos`, so the document contradicted the
  implementation. Resolved inside the declared 17-line correction budget by
  making the **document** match the code and saying why in the code: an empty
  `?categoria=` is the URL of a client that always appends the parameter, so
  answering it with an empty catalog would hide the whole dataset, while
  no-filter is the documented baseline. Lesson: writing a deviation into the
  Evidence section is **not** a spec — the contract has to say what the code
  does, or the next reader (human or reviewer) is right to call it a defect.
- **Blocked**: the `provider_targeted_validator` capture (the only remaining
  step of that correction) is rejected by the facade with
  `collectBinding is missing or stale for current STATUS` although the binding
  is byte-identical to the fresh bound STATUS offer that renders it — the same
  defect recorded for the packaging-tokens round (five failed attempts across
  three lineages). One attempt, then stop: the lineage stays in
  `correction_required` with nothing burned, no verdict written and no
  authority granted. Delivery is the owner's decision, as always.
