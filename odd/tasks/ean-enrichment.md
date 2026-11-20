# EAN enrichment — turn La Anónima into a joinable chain

Branch: `feat/ean-enrichment` (from `main@8ac0dc0`).

## Why

The comparator's ceiling is the identity of the product, not the size of the
catalog. Measured on the local catalog: the three chains that publish a barcode
join at 34 %, 66 % and 67 %, while the two that do not join at 12-13 % — and
those two carry 18 000 of the 31 337 rows.

## The search (read-only, measured against the live sites)

| Chain | Surface | Barcode? |
| --- | --- | --- |
| La Anónima | category `ItemList` JSON-LD | no — only `name`, `url`, `image`, `offers` |
| La Anónima | **product page** JSON-LD `Product` | **yes: `gtin`** |
| SuperMami | `view_item_list` payload | no — `item_id`, `item_name`, `item_brand`, `price` |
| SuperMami | product page (`/super/producto/_/R-<id>`) | no JSON-LD, no `data-*`, no `dataLayer`, zero EAN-13 digits in 147 KB |
| SuperMami | a VTEX-style API | 403 — it is not VTEX |

Two facts make La Anónima cheap to fix:

1. **The detail URL only needs the id.** `https://www.laanonima.com.ar/x/art_<id>/`
   answers exactly like the canonical `.../<slug>/art_<id>/` (any slug works;
   without a slug it redirects to home). We already store that id as `sku`.
2. **The hit rate is total.** 15 randomly sampled La Anónima products without an
   `ean` returned a `gtin` on 15 of 15 detail pages.

SuperMami, by contrast, publishes no barcode anywhere reachable, so its only
lever is layer-2 name matching. That is recorded here and not attempted.

## Decisions

- **N-1 · Enrichment is its own command, never a step of the scrape.** A full
  La Anónima scrape is ~50 requests; adding 8 200 detail pages would make it
  160× slower for data that only changes when a product is new.
- **N-2 · Site knowledge stays in the scraper module.** `laanonima.detail_url(sku)`
  and `laanonima.gtin_of(html)` hold the URL shape and the JSON-LD extraction;
  the loop lives in a service that receives them as seams. Adding another
  chain later means adding two functions, not editing the engine.
- **N-3 · Idempotent and resumable by construction.** Only documents whose
  `ean` is empty are candidates, an existing `ean` is never overwritten, and a
  product without `gtin` is counted, not dumped into an error.
- **N-4 · The write is a targeted update, not a slice replacement.**
  `replace_products` owns whole slices; enrichment must not touch prices,
  names or `scraped_at`, so the port gains an explicit `update_eans`.
- **N-5 · Rate-limited and bounded.** A configurable pause between requests and
  a `--limit` for sampling, so the first run can be a 50-document rehearsal
  before committing 8 200 requests to a live site.
- **N-6 · Paced by default, abort on consecutive failures.** A backfill of a
  site like La Anónima needs ~1.5 s between detail pages and chunks of a few
  hundred (`--limit`), not 0.4 s over 8 000 requests. And the walk must stop
  at the first sustained refusal: `--max-failures` (default 5) ends the walk
  when that many requests in a row fail, the command prints the abort and
  exits 4 so a shell loop never starts the next chunk. Aborting is the
  correct behaviour: a site that starts refusing is telling you to stop, and
  continuing burns the address you need for the next run. Resume is free
  because the command skips documents that already carry an `ean` — the
  aborted walk loses nothing but the requests it must not make.

## The incident (measured during the first real backfill)

The 50-product rehearsal enriched 50 of 50, and the first real chunk added 75
more — 125 products enriched before the block. The pace was 0.2 s between
detail-page requests (an operator override of the 0.4 s default), and after
roughly 800 requests the site began answering 403 and then blocked the whole
domain for this machine's address: the category listing, the home page and
even `curl` with a modern browser User-Agent all answer 403, so it is an
IP-level block, not a User-Agent one. The other four chains answer normally.

Two design defects it exposed, both fixed:

1. **No brake.** The command counted 700 `failed` in one chunk and
   immediately started the next, hitting the door 1 400 more times.
   `--max-failures` (N-6) is the brake.
2. **An imprudent default.** `--sleep 0.4` over ~8 000 requests is a hammer.
   The default is now 1.5 s (N-6).

## Non-goals

- SuperMami (no barcode published — its next lever is the matcher).
- Backfilling `ean` on the other chains: they already publish it in the list.
- Any change to the matching rule.

## Tasks

### T1 · La Anónima: the detail URL and the `gtin` extraction

`detail_url(sku)` builds `https://www.laanonima.com.ar/x/art_<sku>/` (the slug
is decorative, documented as such). `gtin_of(html)` reads the first
`ld+json` block with `"@type": "Product"` that carries `gtin`, returning the
digits as a string, `None` when absent or unusable.

### T2 · Repository: `update_eans(supermercado, mapping)`

One write per `sku` that matches the document and whose `ean` is empty; returns
how many documents it modified. Never overwrites a non-empty `ean`. Same
`RepositoryUnavailable` translation as the other reads. The in-memory fake
implements the same contract.

### T3 · Service: `enrich_eans(...)`

A pure loop over candidate documents with injected seams (`url_for`,
`extract_ean`, `fetch`, `sleep`, `report`) returning the mapping and a report
of attempted / enriched / without-gtin / failed. No HTTP library, no database,
no Flask.

### T4 · CLI: `enrich-ean [--chain] [--limit] [--sleep]`

Wires the repository, the shared HTTP session and La Anónima's two functions;
prints the report; exits 0. Loads the env file with the same selector rule as
the other commands (`LALISTITA_ENV_FILE`, no default, so it never retargets a
database by accident).

### T5 · Run it and measure — PENDING (owner approval of the run)

```
LALISTITA_ENV_FILE=.env.local python -m api.cli enrich-ean --chain laanonima --limit 50
# a chunked backfill: paced by default (1.5 s), stop on 5 consecutive
# failures, and repeat while it exits 0 — 4 means the site is refusing and
# the next chunk must NOT start
LALISTITA_ENV_FILE=.env.local python -m api.cli enrich-ean --chain laanonima --limit 300
LALISTITA_ENV_FILE=.env.local python -m api.cli enrich-ean --chain laanonima --limit 300
LALISTITA_ENV_FILE=.env.local python -m api.cli coverage
```

The number that matters is the `hiper` row of the per-chain block: from 13.2 %
towards what the EAN-publishing chains demonstrate. An exit code 4 on a
chunk means the site started refusing — stop the loop, wait, and resume
later; it is free because already-enriched documents are skipped.

## Evidence

- Search results and the 15/15 hit rate are recorded above; every probe was
  read-only (HTTPS GETs and Mongo reads, no writes).
- To be filled by T5.

## Review record

- Lineage `review-24d7f2755bff1b6a` (medium, one `review-reliability` lens):
  the reviewer filed **R3-ENV-SEARCH-REGRESSION (CRITICAL)** — real, mine, and
  older than this round: `load_env_file` resolved a relative `.env` against the
  current working directory, while the bare `load_dotenv()` it replaced searched
  upward from the caller's file. `python /path/to/repo/app.py` from another
  directory loaded nothing and fell back to the localhost defaults, which is
  precisely the wrong-database failure the selector exists to prevent.
- Corrected inside a declared 44-line budget: a relative env path is anchored at
  the project root, an absolute one is honoured as given, plus a regression test
  that changes directory and proves the file is still found. Verified by running
  from `/tmp` with `LALISTITA_ENV_FILE=.env.local`: the repo's file loads and the
  settings carry `mongodb://localhost:27017/`.
- **Blocked**: the `provider_targeted_validator` capture of that correction is
  rejected by the facade with `collectBinding is missing or stale for current
  STATUS` — twice, with the byte-exact binding the bound STATUS renders and a
  fresh STATUS between attempts, the same symptom the env-selector lineage hit.
  The lineage stays in `correction_required`: nothing burned, no verdict, no
  delivery authority.
