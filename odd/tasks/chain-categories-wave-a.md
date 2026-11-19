# Chain categories, wave A — SuperMami and La Anónima

Branch: `feat/chain-categories-wave-a` (from `main@3f017a4`, after the
`category-coverage` read path merged).

## Goal

Give the two cheapest chains their whole editable food shelf instead of
`almacen` alone, so the catalog grows where a price comparison is actually
possible. These are the two chains where the code is already generic and only
the declared category set is missing.

## Why these two first

From `category-coverage` the read path can now filter and the `coverage`
subcommand reports multi-chain coverage per category. Both scrapers already
discover their taxonomy at run time:

- **SuperMami** resolves a category from the site menu by exact marker
  `supermami-<categoria>`, and the parent category is the collection scope on
  purpose (its level-2 children sum 2 680 against the parent's 3 210). Adding a
  family is one tuple entry.
- **La Anónima** walks the `n2` nodes nested under a configured `n1` URL; each
  `n2` page embeds its whole product list as JSON-LD. Adding a category is one
  `CATEGORY_NODES` entry, and node ids are site facts, not derivable.

## Measured evidence (read-only, live, 2026-11-21)

Discovery executed through the real scraper methods with a stub context (no
database, no writes):

SuperMami — every candidate family resolves to its Endeca path:

| Family | Path |
| --- | --- |
| `almacen` | `/super/categoria/supermami-almacen/_/N-1tjm8rd` |
| `bebidas` | `/super/categoria/supermami-bebidas/_/N-1500t13` |
| `fresco` | `/super/categoria/supermami-fresco/_/N-1lk72oz` |
| `perfumeria` | `/super/categoria/supermami-perfumeria/_/N-146amvi` |
| `limpieza` | `/super/categoria/supermami-limpieza/_/N-1ceauru` |
| `mascotas` | `/super/categoria/supermami-mascotas/_/N-vihosx` |

`fresco` is singular on purpose (it covers carnes, frutas y verduras, lácteos
and congelados as children); there is no `frescos`.

La Anónima — `n2` nodes found under each `n1`:

| Category | n1 id | n2 nodes |
| --- | --- | --- |
| `almacen` | 512 | 11 |
| `bebidas` | 513 | **7** |
| `lacteos-y-frescos` | 516 | **5** |
| `congelados` | 766 | **7** |
| `frutas-y-verduras` | 517 | **2** |
| `carniceria` | 518 | **5** |
| `perfumeria` | 820 | **6** |
| `limpieza` | 514 | **7** |
| `mascotas` | 877 | **0 — leaf** |

`mascotas` is a **leaf n1**: its `li` in the menu carries no `menu-n2` anchor
at all, so the n2-only walk would report "no subcategorías" forever while the
category exists. Its `n1` page does embed a JSON-LD `ItemList` (201 items
measured), and `_scrape_node` reads that block from any page, so the leaf case
is a scope decision, not new parsing.

Out of scope on purpose (not a supermarket price comparison): SuperMami
`electro`, `hogar`, `jugueteria`, `bebe`, `libreria-y-cotillon`,
`aire-libre`, `neumaticos`; La Anónima `tv-y-video`, `celulares-y-telefonos`,
`electrohogar`, `tiempo-libre-deporte-y-entretenimiento`,
`hogar-jardin-y-automotor`, `indumentaria-y-moda`,
`construccion-y-remodelacion-del-hogar`, `bebes-ninos-y-jugueteria`.

## Decisions

- **W-1 · Declare only categories that can actually yield products.** A
  declared category that resolves to nothing is worse than an undeclared one:
  it reports a healthy-looking run with an empty slice. This is why the leaf
  case is handled instead of silently declaring `mascotas`.
- **W-2 · A leaf `n1` is scraped as one node, never silently skipped.** When
  the configured `n1` anchor exists in the menu but has no `n2` children, the
  `n1` page itself is the collection scope and its own slug is the stored
  `subcategoria`.
- **W-3 · An absent `n1` anchor keeps today's loud failure.** "The menu no
  longer lists this category" and "this category has no children" are different
  facts and must not collapse into the same report: the first is a site change
  (a defect on our side), the second is the taxonomy's shape.
- **W-4 · No new pagination, no new cap.** SuperMami keeps `Nrpp=500` with no
  offset ceiling and La Anónima keeps one request per node; the measured node
  sizes are far below anything that would need it.
- **W-5 · The scrape run itself stays the owner's decision.** AGENTS.md rule 7:
  every save replaces a slice. This feature adds the declared categories and
  their tests; actually filling them is one command the owner runs against the
  database he chooses.

## Tasks

### T1 · SuperMami: the six food families — DONE (`35ef567`)

`categories = ("almacen", "bebidas", "fresco", "perfumeria", "limpieza",
"mascotas")`, plus the tests: the tuple is exposed through `/api/scrapers`, a
run over several families saves one slice per family (its own `categoria`), and
a family the menu does not list still raises instead of ending as a success.

### T2 · La Anónima: nine `n1` categories and the leaf case — DONE (`896927f`)

`CATEGORY_NODES` gains the eight measured n1 URLs and `categories` lists the
nine keys; `_discover_nodes` returns `None` when the anchor is missing and `[]`
when it exists with no children, so `run()` can apply W-2 and W-3.

Acceptance: the menu-missing test still saves nothing and says so; a leaf
category scrapes its `n1` page and stores it under its own slug; a leaf page
without an `ItemList` is reported and the run continues; every other category
keeps one save per `n2` node.

### T3 · Live discovery verification — DONE

Both scrapers' discovery methods were executed against the live sites with a
stub context before writing the tuple (tables above). No database, no writes.

### T4 · Owner run and coverage measurement — PENDING (owner)

Blocked on one decision: `python -m api.cli run` does **not** load `.env` (only
`coverage` does), so a scrape writes to whatever `MONGODB_URI` the shell has —
the local `mongod` by default, which is not the catalog the dashboard reads.
Either export `MONGODB_URI` for the run or decide that `run` should load `.env`
like `app.py`. Then:

```
python -m api.cli run supermami
python -m api.cli run laanonima
python -m api.cli coverage      # baseline today: almacen 21 293 docs / 18.1%
```

The number that matters is whether `bebidas` and `limpieza` show a multi-chain
share above `almacen`'s 18.1 %: if they do, the next wave is about category
coverage; if they do not, the matcher is the bottleneck and categories will not
fix it.

## Evidence

- **Gates**: whole suite 531 passed / 16 skipped (opt-in MongoDB), flake8 CI
  gate 0. Both scraper files green test-first: T2 RED was 6 failures before the
  implementation, T1 RED was 4.
- **The registry surface moved with the tuple**: `python -m api.cli list` prints
  `supermami: ... (almacen, bebidas, fresco, perfumeria, limpieza, mascotas)` and
  the nine La Anónima categories, and
  `tests/test_container.py::test_default_app_lists_the_registered_scrapers`
  pinned `["almacen"]` for SuperMami — it now pins the six, which is the contract
  the wider tuple exists to expose.
- **`run()` semantics for La Anónima changed shape**: it used to resolve one
  category and return; it now walks every declared category unless `--category`
  narrows it, keeping one final `PROCESO DETENIDO`/`PROCESO TERMINADO` report.
  A category whose menu can be read but lists no anchor is reported and skipped
  instead of ending the whole run — with nine categories, one changed path must
  not block the other eight.
- **Merged** to local `main` as a fast-forward (`3bff01a`); `main` is 16 commits
  ahead of `origin/main` and nothing was pushed.
- **Native review**: `inspect` timed out twice on the native `review/status`
  (retry answered), then START failed twice the same way before succeeding, so
  the first three attempts looked like a dead facade and were not. Lineage
  `review-addbe7d3471d8431` (tier medium, one lens `review-reliability`,
  25 paths / 2 216 changed lines) came back **approved**, and its
  acknowledgement burned the authority (`native-approved-acknowledgement-completed`).
  Two advisory findings were attached, both `WARNING` and non-blocking:
  `api/cli.py:118` and `tests/test_product_repository.py:253`. Their full claim
  text was not part of the closure payload, so they are recorded here as
  follow-ups to read, not as defects to guess at.
- **A rejection is not always a defect.** One capture was refused with
  `collectBinding is missing or stale for current STATUS` because the hand-copied
  binding had a corrupted `schema` URL (`https://gentle-ai/review/...` instead of
  `https://gentle-ai.dev/schema/review/...`). Re-submitting the byte-exact
  binding was accepted immediately. Verify the copy before concluding the facade
  is broken.

## Non-goals

- Carrefour and ChangoMás (wave B; Carrefour needs the 2 550-node strategy).
- Disco (wave C; the `fq=P:` price filter stores 12 % of its published catalog).
- Frescos by weight at any chain (price-per-kg modelling).
- Canonical category vocabulary: the slugs stay the site's own.
