# Review follow-ups (T4 findings that survive at HEAD)

Branch: `feat/backend-architecture`. Origin: the escalated native review of T4
(`052aeda`, lineage `review-01c9eb1c9532c735`). That lineage is terminal and cannot
be reopened; the findings below were re-verified against HEAD and only the ones that
still hold are in scope.

## Out of scope, with the reason

| Finding | Why it is not fixed here |
| --- | --- |
| `R3-001`, `R4-002` | Moot at HEAD: the legacy scrapers are gone (deleted in `30b20cb`), and both writes and reads now go through `MongoProductRepository(app.database)` |
| `R4-001` | Refuted by the provider refuter, and deliberate: `changomas`/`supermami` declare `categories = ()` and `validate_category` documents that a category-less scraper ignores the value |
| `R2-003` | `api/routes.py` no longer exists, so its stale line citations are gone with it |
| `R2-004` | Already fixed: T4 is `[x]` in `backend-architecture.md` |
| `R3-003` | Product decision (empty `SECRET_KEY` falls back to `secret!`), not a mechanical fix; tracked with K-13 |

## Tasks

- [x] **T1 — `/supermercados` error path tells the truth** (`R3-002`, `R2-001`).
  A database failure must keep emitting the legacy `Error reading from MongoDB`
  signal that alerting and log searches rely on, and a non-database defect must not
  be reported as `Database connection error`. Introduce a repository-level
  unavailable error, translate driver errors to it in the Mongo adapter, and split
  the blueprint's `except` into database vs unexpected.
- [x] **T2 — RUNNING is never lost to a fast scrape** (`R3-004`, `R2-005`).
  Deliver the RUNNING snapshot before the worker can advance the version, and record
  a version as delivered only after the reporter accepted it, so a reporter failure
  does not burn the notification.
- [x] **T3 — the real-Mongo teardown guard is real** (`R1-2`). The guard must derive
  its assertion from the database actually about to be dropped instead of comparing
  the constant with itself.
- [x] **T4 — document the catalog tie-break** (`R2-002`). The
  `supermami + carrefour + hiperlibertad + disco` concatenation is a stable-sort
  tie-break contract, not an arbitrary order.

## Evidence

Commit `e16d32b` (`fix: address the review findings that survive at HEAD`), 11 files,
+424/−39. Delivered through `gentle-ai-worker` and closed against the notes of an
independent `gentle-ai-verify` pass (PASS-WITH-NOTES): the unstarted-thread `wait()`
window, the stale invariant comment, the untested ghost-correction delivery, the
port/error placement, the doc counts and the teardown client leak were all closed in
the same unit.

- `pytest -q` → **291 passed, 9 skipped** (baseline 281 + 10 new tests).
- `tests/test_scraper_manager.py` → 33 passed, identical across 10 consecutive runs.
- flake8 CI gate → `0`.
- RED observed before each behaviour fix: `RepositoryUnavailable` import failure,
  `['succeeded'] != ['running', 'succeeded']`, the burned-version assertion, the
  missing `_drop_throwaway` helper, and `RuntimeError: cannot join thread before it
  is started` from a re-entrant reporter.

## Verification

`pytest` (full suite) plus the flake8 CI gate
(`flake8 . --exclude .venv,adminpro,static,node_modules --select=E9,F63,F7,F82 --count`).
T1 and T2 need tests that fail first: a non-database defect answering a distinct
label, and a fast scraper whose RUNNING notification is still delivered.
