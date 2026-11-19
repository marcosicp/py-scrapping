# Price integrity — stop storing $0 as "no price"

Branch: `fix/price-integrity` (from `main@e79dcfc`).

## Goal

A price comparer that shows `$0` is worse than one that shows nothing: the
user reads `$0` as a real offer. Today one quarter of the grouped rows carry a
zero price, and 1 219 of them put that zero next to a real price from another
chain.

## Measured baseline (read-only, on the deployed database)

Documents with `price = 0`:

| Chain | Docs | `price = 0` | Share |
| --- | --- | --- | --- |
| ChangoMás | 4 099 | **2 602** | **63 %** |
| Carrefour | 6 187 | **1 477** | **24 %** |
| Disco | 4 720 | 1 | ~0 % |
| La Anónima | 3 036 | 1 | ~0 % |
| SuperMami | 3 251 | 0 | 0 % |

In the payload the dashboard serves (16 588 rows):

- **3 998 rows (24.1 %) carry at least one `$0`**;
- **1 219 rows are comparable (2+ chains) and show a `$0` beside a real price** —
  the exact case where the product answers "where is it cheaper" with a lie.

The user's own query, `aceite de oliva 250`: 74 rows, 24 comparable, **29 with a
`$0`**.

## Root cause

`api/scrapers/{changomas,carrefour,disco}.py` share the same three lines:

```python
sellers = items[0].get("sellers") or []
offer = sellers[0].get("commertialOffer") or {}
price = offer.get("Price")
...
return price   # or 0 when absent
```

Two defects in one function:

1. **`sellers[0]` is read without checking `IsAvailable`.** VTEX lists several
   sellers per SKU; the first can be an unavailable one carrying `Price: 0.0`
   while a later seller carries the real price.
2. **`0` is the "unknown" value.** An unavailable SKU and a genuine zero are
   indistinguishable downstream, and both render as `$0`.

Measured on a random sample of 40 zero-price documents per chain, resolved
against the live API:

| Chain | Recoverable today | Where the price was | Genuinely unavailable |
| --- | --- | --- | --- |
| ChangoMás | 7 / 40 (18 %) | **all 7 in `items[0]`, later seller** | 33 / 40 |
| Carrefour | 0 / 40 | — | 40 / 40 |

Across both samples, **0 of 80 needed a different `items[k]`**. One concrete
example: our stored `Ketchup Danica` sits at `$0` while the API answers
`$1.519` available.

Disco shows the same code and almost no zeros **because its price filter
(`fq=P:[0.01 TO …]`) keeps unpriced products out of the collection entirely** —
the defect is masked there, not absent.

## Decisions

- **P-1 · Never store `0` for "no price".** The value is `None`. A null price
  renders as a blank cell, which is the truth; a zero renders as a price.
- **P-2 · Pick the first *available* seller with `Price > 0`;** if none is
  available, the first seller with `Price > 0` (a listed but out-of-stock price
  is still a real price); otherwise `None`. Non-numeric, boolean and
  non-positive values never win.
- **P-3 · Stay inside `items[0]`.** The stored `ean` is `items[0].ean`, so a
  price from another SKU would be attached to the wrong identity and would
  poison the EAN layer of the matcher. The measurement says it is not needed.
- **P-4 · One implementation, not three.** Three copies of this rule produced
  the same defect three times; the rule moves to `api/scrapers/vtex.py` and the
  three scrapers call it. That is the difference between fixing the symptom and
  fixing the cause.
- **P-5 · La Anónima is out of scope this round.** It parses a JSON-LD
  `offers.price` (Endeca, not VTEX), carries 1 zero out of 3 036 documents, and
  its `0`-when-missing rule is documented and tested. Changing it would add
  surface with no measured loss behind it; recorded as a follow-up instead.
- **P-6 · The fix lands on the next scrape, not retroactively.** Stored zeros
  are replaced when each chain's slice is rewritten; until then the dashboard
  keeps showing them.

## Non-goals

- Matching (the other measured bottleneck, 18.1 % multi-chain).
- Hiding `$0` in the frontend: the payload will stop producing them, and a
  display patch would hide the next regression.
- Any category work (waves B and C stay parked).

## Tasks

### T1 · One price rule for the VTEX scrapers

`api/scrapers/vtex.py` gains the P-2 rule; `changomas`, `carrefour` and `disco`
call it from their `_price_of`. Keep each module's public shape and docstrings
intact apart from the delegation note.

Acceptance: three scrapers, one rule, no behaviour left duplicated.

### T2 · Tests for the rule and its callers

Table-driven tests over the payload shapes that matter: first seller
unavailable + second available; no available seller but a positive price; every
offer `Price: 0`; no sellers; no items; `Price` as a string, a bool or `None`.
Plus one test per scraper proving the document price follows the rule and is
`None` — never `0` — when nothing is available.

### T3 · Frontend: verify, do not patch

`selection.ts` already treats an unusable price as zero for the totals and the
grid cell renders a null price as blank, asserted by
`npm run verify:selection` ("total ignores an unusable price"). Re-run it and
record the evidence; no code change is expected.

### T4 · Owner run and verification — PENDING (owner)

After `run changomas` and `run carrefour` against the chosen database:

```
python -m api.cli coverage
```

and a zero-price count. Expected: `price = 0` documents drop to 0, the document
count stays the same, and the 1 219 misleading rows disappear. The multi-chain
percentage must not move — this fix changes prices, not joins.

## Evidence

- Baseline, root cause and the 40-per-chain resolution sample are recorded above
  with their exact figures; every probe was read-only (Mongo reads and VTEX
  `products/search` GETs, no writes).
