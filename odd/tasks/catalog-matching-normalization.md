# Feature — Normalize catalog identity: one row per real product

Owner request (2026-11-10): *"aceite girasol pureza"* in `1,5 lt` and `1500 cc`
appears as two rows — one from La Anónima, one from Carrefour — when both are the
same product. *"Me parece que tenemos que optimizar o normalizar el guardado de
los datos."*

Branch: `fix/catalog-matching-normalization` (base `main` `f9c45e5`).

## 1. What actually breaks

The unit normalization the request suspected **already works**: `_UNIT_FAMILIES`
in `api/services/matching.py` maps `lt`/`lts` → ×1000 ml and `cc` → ×1 ml, so
`1,5 Lt` and `1500 cc` both yield `qty=1500.0, family="ml"`. The join is lost
somewhere else.

Live reproduction (`lalistitadev.productos`, 2026-11-10):

```
solo | Aceite de Girasol Pureza x . | 1,5 Lt  | {hiper: 7900}
solo | Aceite de Girasol Pureza x . | 900 cc  | {hiper: 5000}
ean  | Aceite de girasol Pureza     | 1500 cc | {carre: 7465, disco: 7850, chang: 7469}
ean  | Aceite de girasol Pureza     | 900 cc  | {carre: 4780, disco: 5000, chang: 4729}
```

| Chain | name | unidad | brand | ean |
| --- | --- | --- | --- | --- |
| Carrefour | Aceite de girasol Pureza | `1500 cc` | `Pureza` | `7792180137944` |
| Disco | Aceite Girasol Pureza 1.5 L | `""` | `PUREZA` | `7792180137944` |
| ChangoMás | Aceite De Girasol Pureza 1.5 L | `""` | `Pureza` | `7792180137944` |
| La Anónima | Aceite de Girasol Pureza x . | `1,5 Lt` | `""` | — |

### C1 — La Anónima carries no brand, and D-11 demands brand equality

`api/scrapers/laanonima.py:205` hardcodes `brand: ""`: **0 of 3 036** La Anónima
documents carry a brand, against 100 % on the other four chains. Layer-2's D-9
rule already tolerates that (`_joins_strict`: brands must be equal *when both
sides carry one*), but the layer-1/layer-2 reconciliation compares
`_signature(group)` — which includes `brand` — for exact equality. A brandless
document can therefore never join an EAN group of a branded product. This is an
internal inconsistency between D-9 and D-11, not an edge case: it hits every La
Anónima document whose product also exists on Disco or Carrefour.

### C2 — A group's identity is set by whichever document arrived first

`_Group` copies `tokens`/`qty`/`family`/`brand` from its first member. Inside
EAN `7792180138705` live Carrefour `Alto Omega pureza 15 l`
(`qty=15000.0, family="ml"`) and ChangoMás `Alto Omega 1.5 L.`
(`qty=1.5, family=None`). Measured: of **2 644 EAN groups with 2+ documents,
2 270 (86 %) have members with inconsistent tokens/qty/family** — so which rows
merge depends on insertion order.

### C3 — A presentation left in the name pollutes the token set

`api/helpers.py::name_parse` has `lt|lts` but **not a bare `l`**, so
`Aceite Girasol Pureza 1.5 L` keeps `unidad=""` (**102 names** in the catalog).
Matching then falls back to the name and consumes `"1.5"`, but
`_name_tokens` splits on `[^0-9a-z]+`, so the live tokens are `'1'`, `'5'` —
not in `consumed`, so they survive. Disco ends up with
`('1','5','aceite','girasol','pureza')` and La Anónima with
`('aceite','girasol','pureza')`: the same product with two identities.

## 2. Measured impact of the fixes (21 293 documents)

Baseline: **17 200 rows, 14 267 single-chain rows**.

| Variant | rows | single-chain | owner's case |
| --- | --- | --- | --- |
| baseline | 17 200 | 14 267 | split |
| D-11 brand-agnostic, first-doc signature | 16 894 (−306) | 13 835 (−432) | joined |
| D-11 brand-agnostic, consensus signature | 16 810 (−390) | 13 802 | **still split** (C3 poisons the key) |
| C3 clean tokens + D-11 document-level | **16 614 (−586)** | **13 625 (−642)** | **joined** |

The last combination promotes **1 014 documents** from layer 2 to layer 1 and
moves no price.

## 3. Decisions

- **D-20 · Reconcile per document, not per group.** A document without `ean`
  joins layer 1 when its own `(tokens, qty, family)` points at exactly one EAN,
  with `qty` and `family` resolved, and brands compatible per D-9 (equal when
  both sides carry one). This removes C1 and C2 together: no brand required, no
  dependence on insertion order.
- **D-21 · The fail-open bias is preserved, not weakened.** Ambiguity still
  keeps rows apart: 362 `(tokens, qty, family)` keys point at 2+ distinct EANs
  and stay ungrouped. A false positive corrupts the price comparison; a false
  negative only repeats today's behavior (D-2).
- **D-22 · This deliberately retires one D-11 guardrail.**
  `test_loose_layer2_group_never_absorbs_into_a_strict_ean_group` pinned the old
  "a brandless document never joins an EAN group" rule; that rule is exactly what
  the owner reported as broken. The test is rewritten to the new contract, and
  the cases where the guard must still hold (brand conflict, ambiguous key,
  unresolved presentation) keep their own tests.
- **D-23 · Unit vocabulary is shared knowledge, not two regexes.**
  `helpers.name_parse` gains the bare `l` and the unit set becomes one ordered
  tuple (`UNIDADES`) instead of a vocabulary buried inside the regex; both are
  pinned by tests so they cannot drift silently again. The bare `m` stays:
  dropping it was an unrequested behavior change that altered how metre-length
  names are stored, caught by the review (R3-001) and reverted in `c140980`.
  Matching cannot resolve `m` as a unit family, which was the original
  motivation — but "matching ignores it" is not a reason to change what the
  scrapers store.
- **D-24 · Query-time only, no re-scrape.** Matching is computed on every
  request from stored documents, so no catalog rewrite is required.

## 4. Tasks

| # | Task | Evidence |
| --- | --- | --- |
| T1 | Feature document + tasks mirror | this file, Engram `odd/catalog-matching-normalization/tasks` |
| T2 | RED: document-level reconciliation tests (owner's case, brand conflict, ambiguity, order independence) | `pytest` → 2 failed, 28 passed |
| T3 | GREEN: document-level reconciliation in `matching.py` | `656d01a` · 30 passed · catalog 17 200 → 16 667 rows |
| T4 | RED+GREEN: `consumed` survives the token split | `9f16796` · 32 passed · 31 documents change token set |
| T5 | RED+GREEN: `name_parse` reads a bare `l` | `3006dd0` · full suite 468 passed / 9 skipped, flake8 gate 0 |
| T6 | Full-catalog re-measure + docs + close | section 5 |
| T7 | Correction after review R3-001 (keep `m`) | `c140980` · suite still 468 passed / 9 skipped |

## 5. Result (live catalog, 21 293 documents)

| | rows | single-chain rows | owner's case |
| --- | --- | --- | --- |
| before | 17 200 | 14 267 | 4 rows |
| after | **16 667** | **13 703** | 1 row, `{carre, disco, chang, hiper}` |

- 533 fewer rows (−3.1 %) and 564 fewer rows showing a single chain.
- **988 offers from the two chains that never persist an EAN** — 503 La Anónima
  (`hiper`) and 485 SuperMami (`mami`) — now sit inside an `ean` row instead of
  carrying a row of their own; 2 867 of the 16 667 rows are EAN rows.
- The owner's pair now renders as one row:

  ```
  ean | Aceite de girasol Pureza | 1500 cc | carre 7465 · disco 7850 · chang 7469 · hiper 7900
  ```

- No price is modified: matching only decides which documents share a row.
- No re-scrape needed (D-24): `grouped_catalog()` recomputes on every request.

## 6. Verification

1. Tests first at every step (`tests/test_matching.py`, `tests/test_helpers.py`).
2. Full `pytest` at the close: **468 passed, 9 skipped** (the 9 are the opt-in
   MongoDB integration tests; no network, no DB, no Chrome).
3. `flake8 . --exclude .venv,adminpro,static,node_modules --select=E9,F63,F7,F82
   --count` → 0.
4. Read-only re-measure script over `lalistitadev.productos` for the row counts
   and the Pureza row above.
5. Frontend: no change needed, the payload shape is identical — only grouping.
   The owner's manual round is still the UI evidence (AGENTS.md §8).

## 7. Native review (scoped lineage `review-186f38355fa69536`)

Owner decision: review **scoped to these four commits** rather than the whole
unpushed range, because the provider's default base-ref bundles the previous
round's dashboard spinner (already left unreviewed by the owner) and a
`dev.sh` commit from an earlier session. `START` with
`baseRef=f9c45e55810e37c52c3cc04e2ced23abea85bb2c, committedOnly=true`:
tier medium, one lens `review-reliability`, 7 files / 426 lines, correction
budget 200.

Findings and dispositions:

| Finding | Severity | Disposition |
| --- | --- | --- |
| `R3-001` — dropping `m` from the unit set changes stored metre-length names | CRITICAL | **Real, fixed in `c140980`** (correction declared as 22 diff lines) |
| `R3-002` — "the C3 decimal fix leaves a `1` token for `1.5 L`" | WARNING | **False positive**: `_presentation` reads whitespace tokens (`"1.5"` is whole) and `_name_tokens` runs after it, so `_consume("1.5", "l")` covers the pieces |
| `R3-003` — the name-number guard test proves nothing | WARNING | Accepted: the positive case is weak. Follow-up |
| `R3-004` — the insertion-order test uses a single EAN document | WARNING | Accepted: it does not exercise a multi-document EAN group. Follow-up |

After the correction was committed, `STATUS` offered the targeted-validation
slot (`request_hash sha256:cebd1928…`) and every replay of that exact binding
was rejected with `capture-binding-rejected: collectBinding is missing or stale
for current STATUS`, including one with no acknowledgement flag — the binding
carries `expected-revision sha256:d8b7adf7…` while `STATUS.authority.revision`
reads `sha256:d670ef3d…`, so the two never line up. `capture` was not retried
further: a slot that cannot be satisfied through the facade is a blocked human
decision, not something to replay. Lineage left open; nothing in the review
authority was mutated.

## 8. Residual risks and follow-ups

- A brandless document can still join the wrong EAN group when two physical
  products share `(tokens, qty, family)` and only one of them has an EAN. Tokens
  carry the brand word in almost every name, so the practical surface is small,
  and the 362 ambiguous keys stay split.
- La Anónima still stores `brand: ""` for every document. Matching no longer
  needs it; extracting brands from names is scraper-side heuristics and was
  deliberately not attempted.
- `name_parse` leaves the punctuation that followed the unit (`... pet 1 l.` →
  name `... pet .`). Pre-existing for every `... 160 g.` name; cleaning it up
  changes stored names, so it needs its own decision.
- **R3-003 follow-up**: `test_numbers_that_belong_to_the_name_are_not_consumed`
  should compare a name number that only one side carries (`120 Años` vs
  `Años`) so the assertion fails if `_consume` ever eats an independent number.
- **R3-004 follow-up**: `test_brandless_join_does_not_depend_on_insertion_order`
  should use a two-document EAN group whose members disagree (Carrefour
  `1500 cc` + Disco `1.5 L`, `unidad=""`) — the shape that made C2 possible.
- `price = 0.0` on 1 477 Carrefour documents is a separate known defect
  (`docs/agent-context/known-issues.md`) and is out of scope.
