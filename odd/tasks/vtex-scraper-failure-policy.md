# Feature: VTEX scrapers — fatal page failures and fatal discovery

STATUS: DONE — `fea32df` plus the D3 correction below, on `main`
Owner request: "arreglemos R3-001 y R3-002".

Closes the two follow-ups recorded at the end of
`odd/tasks/changomas-chain-integration.md`.

## Why

The native review of the ChangoMás round produced two findings. One was
corrected in `changomas.py` inside the frozen correction scope; the instances
in the other VTEX scrapers were explicitly left as follow-ups. Both are real and
both survive in code today.

**R3-001 — a page failure must not save a truncated slice.**
`replace_products` REPLACES a scraper's `supermercado`/`categoria` slice. A
scraper that `break`s out of a page loop on a network error, a non-2xx response
or invalid JSON returns the documents collected so far, the caller saves them,
and the run reports success — so one transient failure silently truncates the
stored catalog.

| Scraper | State before this task |
| --- | --- |
| `changomas.py` | **fixed** in the review correction: reports that the partial collection is not saved, then raises |
| `disco.py` | already correct: 4xx raises at once, 5xx/network retry then re-raise |
| `carrefour.py` | **open**: all three failures report and `break` |

**R3-002 — a declared category missing from the tree must fail, not succeed.**
`_discover_subcategories` returns `[]` when the requested category is not found
in the VTEX tree. `run` then reports "no subcategories", saves nothing and ends
as a **success** with zero products. If the site renames or removes the path,
the run looks healthy and collects nothing.

The helper is **byte-identical in all three VTEX scrapers** — it was
copy-pasted, so the finding is not limited to the two files it names:

| Scraper | Test currently pinning the silent success |
| --- | --- |
| `carrefour.py` | `test_a_category_missing_from_the_tree_saves_nothing_and_says_so` |
| `disco.py` | `test_a_category_missing_from_the_tree_says_so_and_the_run_continues` |
| `changomas.py` | `test_a_category_missing_from_the_tree_saves_nothing_and_says_so` |

`disco.py`'s test goes further and **asserts that the run continues**, so the
behaviour was pinned on purpose, not left by accident.

## Decisions

**D1 — R3-001 is fixed in `carrefour.py` by aligning it with `changomas.py` and
`disco.py`.** The three page failures report that the partial collection will
not be saved and then raise, so `run` never reaches `ctx.save` for that
subcategory: the previous slice stays intact and the manager marks the run
failed. `if not items: break` stays, because an empty page is how the API
signals the end of a catalog. No retry/backoff is added to Carrefour: adding the
Disco retry policy is a separate behaviour change that the finding did not ask
for.

**D2 — R3-002 is fixed in all three scrapers, not only the two it names.** A
declared category that cannot be resolved is fatal: report and raise. The
duplication is the reason the same defect exists three times, and fixing two
would leave the third silently collecting nothing.

**D3 — A resolved category with no usable children is reported and
skipped.** — REVISED after review; the original wording made it fatal.

The first version argued that an empty node has "the same harm" as a missing one
and raised for both. The native review rejected that as scope creep and called
it CRITICAL: R3-002 only required a **missing** category to fail, the baseline
skipped an empty one and continued with the remaining categories, and failing
the whole run means one legitimately empty category blocks every other one — a
real regression for `carrefour.py`, which declares two categories.

Restored behaviour: the empty node is reported (`Sin subcategorías que recorrer
en <categoria>; se continúa con la siguiente`) and the loop moves on. Only the
missing node raises. The lesson is worth keeping: "same class of harm" is not a
mandate to widen a finding beyond what it asked for.

**D4 — Dead branches are deleted, not left unreachable.** With `_fetch_tree`
already raising on every failure, `if tree is None: return []` cannot run; with
`_discover_subcategories` raising instead of returning `[]`, `run`'s
`if not subcategorias: continue` cannot run either. Both go.

**D5 — The pinning tests are inverted, not deleted.** Each keeps its intent and
asserts the new contract. `test_a_page_that_is_not_2xx_is_reported_and_the_next_
subcategory_runs` is the important one: it asserts the R3-001 defect by name, so
it becomes the regression test for the fix.

**D6 — Out of scope.** `carrefour.py` keeps the tree in a **class** attribute
(`_tree = None`), a cross-run cache in one process; `disco.py` and
`changomas.py` cache per instance and `tests/test_scraper_disco.py` punishes the
class-level shape. Real, unrelated, and left alone.

## Tasks

- [x] T1 — `carrefour.py`: fatal page failures (R3-001) + invert the pinning
      test.
- [x] T2 — R3-002 in `carrefour.py`, `disco.py` and `changomas.py`: fatal
      discovery, dead branches removed, three pinning tests inverted.
- [x] T3 — Verification and the doc lines this invalidates.

## Review correction (D3)

`review-e0e9ea2396c6128c` (tier medium, one lens, 7 files / 395 lines) raised one
CRITICAL, deterministic, introduced finding against this candidate:

> The candidate makes a resolved category with no usable children fatal in all
> three VTEX scrapers, aborting the whole run. The baseline skipped such a
> category and continued scraping the remaining categories; R3-002 only required
> a missing category to fail. One empty category now prevents other categories
> from being scraped.

Corrected as described in D3. The three tests that pinned the overreach
(`test_a_tree_node_without_usable_children_fails_the_run`, one per module) are
inverted to
`test_a_tree_node_without_usable_children_is_skipped_not_fatal`, which asserts
the run completes, saves nothing, reports the skip and reaches
`PROCESO TERMINADO`. A missing category still raises, and each module keeps that
test.

## Correction after the second review (R3-1)

The fresh lineage for the D3 correction
(`review-6a71a145c39d12a1`) raised one CRITICAL, deterministic, introduced
finding — again about overreach, this time in operator-facing output:

> The empty-category path changes the existing user-visible message from the
> baseline `No se encontraron subcategorías de ...` to `Sin subcategorías que
> recorrer ...` and also adds a new `La categoría ... existe ...` report in
> `_discover_subcategories`; R3-002 only required a missing category to fail,
> so these output changes are unrequested.

Corrected: both messages are back to the baseline wording, and the helper no
longer reports anything on the empty-node path — the caller owns that report,
exactly as before. The missing-node raise stays.

The same lesson as D3, one level down: **a finding licenses the smallest change
that closes it, not a rewrite of the surrounding prose.** Inventing better
messages was not asked for and is a real cost for anyone reading logs.

## Correction after the third review (R3-001)

`review-78d4e9da2cdc4db3` raised the same class of finding a third time:

> The candidate appends `No se guarda la recolección parcial` to the existing
> network, non-2xx and invalid-JSON failure messages in `_scrape_subcategory`,
> changing operator-facing output beyond the requested fatal-failure behaviour.
> R3-001 only required that a page failure not save a truncated slice.

Corrected: Carrefour's three failure reports are back to their original
wording; only the control flow changed (`break` → `raise`). The test asserts a
message starting with `Error` / `Respuesta inválida` instead of the invented
suffix.

The pattern across the three findings is now explicit and worth stating once:
**the reviewer is enforcing minimality, not correctness.** Each finding was a
real deviation from "only what the finding asked for", and each one was in
prose rather than logic. The audit that should have been done up front:
`git diff <base> -- api/scrapers/ | grep '^[+-].*ctx\.report'` — it lists every
operator-facing string the candidate adds or removes, and it is nine lines.

After this correction the only new report in the whole candidate is the missing
node's, which is the behaviour R3-002 asked for.

## Verification observed

`python -m pytest -q` → **459 passed, 9 skipped** (454 before). flake8 CI gate
(`--select=E9,F63,F7,F82`) → `0`.

- RED observed before GREEN: 9 failures, all `DID NOT RAISE RuntimeError` — the
  inverted and new tests failing against the old silently-successful behaviour.
- The three `_discover_subcategories` bodies are **byte-identical** afterwards
  (same md5), which is the point: the duplication is why the defect existed
  three times.
- Dead branches verified gone: `grep -n "tree is None\|if not subcategorias"`
  over `api/scrapers/` finds only `laanonima.py:66`, a different subsystem (see
  follow-ups).
- Carrefour's page failures now report `No se guarda la recolección parcial` and
  raise, exactly like `changomas.py`; no retry policy was added (D1).
- The parametrised regression test covers network error, non-2xx and invalid
  JSON mid-paging and asserts the run raises, nothing is saved and no
  `PROCESO TERMINADO` is reported.

After the R3-1 correction: baseline wording present once per scraper, the
invented strings gone (`grep -c` → 0 in each), the missing-node raise intact,
and the three helpers still byte-identical (same md5).

After the D3 correction: `python -m pytest -q` → **459 passed, 9 skipped**,
flake8 gate `0`, and the three `_discover_subcategories` bodies are still
byte-identical (same md5). `grep -c "is not in the category tree"` → 1 in each
scraper (missing stays fatal); `grep -c "no usable subcategories"` → 0 in each
(the empty node no longer raises).

Not verified: a live scrape. The failure paths need a real network fault to
exercise end to end and no test touches the network by design.

## Follow-ups

- `carrefour.py`'s class-level `_tree` cache (D6).
- `laanonima.py` has the same silent-success shape in a different subsystem:
  `run` returns cleanly when the category has no configured node
  (`laanonima.py:62-64`) or when the navigation menu yields no subcategories
  (`laanonima.py:66-69`), so a site change there ends as a success with zero
  products. Not fixed here: it is a JSON-LD/menu scraper, not VTEX, and the
  findings did not name it.
- `disco.py` has its own retry/backoff policy for search windows that
  `carrefour.py` and `changomas.py` do not share; the three VTEX scrapers are
  still three copies of the same shape. Extracting a shared module remains
  deliberately undone: it would rewrite Disco's tested policy.
