# Feature — one row per product: the packaging word must not split it

Owner report (2026-11-18): *"vimos productos que son los mismos pero a veces,
según el supermercado, cambia la presentación, aunque es lo mismo. Aca de nuevo
te paso un ejemplo: 200 ML es lo mismo que 200 CC, lo vi en el producto 'aceite
oliva extra virgen cocinero'."*

This is the follow-up of [`catalog-matching-normalization.md`](catalog-matching-normalization.md)
(D-20..D-24), which normalized the layer-1/layer-2 reconciliation per document.

Branch: `fix/product-packaging-tokens` (base `main` `6afbbc8`).

## 1. What actually breaks

### C4 — the unit spelling the owner suspects is already one family

`_UNIT_FAMILIES` (`api/services/matching.py:48`) maps `ml`/`mls`/`cc` → factor
1, base `ml`, and `l`/`lt`/`lts` → ×1000 ml. `200 ml` and `200 cc` both yield
`qty=200.0, family="ml"`, i.e. the same layer-2 key. Verified live: `Vinagre de
Alcohol Casalta` 500 cc (La Anónima) + 500 ML (SuperMami) already share one row,
and the Cocinero 500 cc row already carries SuperMami's `500 ML` document.

There is **no** Cocinero in 200 ml/cc in the catalog at all — the stored sizes
are 250, 500, 900 and 1000. The number in the report is approximate; the
phenomenon is real and it is the one measured below.

### C5 — the residual cause is the packaging word

Only some chains name the container, and a name token is part of the layer-2
identity, so the same product in the same size sits in two rows whenever the
EAN layer cannot join them — which is exactly the case for SuperMami and
La Anónima, the two chains that never persist an `ean`.

Measured over the live catalog the app reads (`lalistitadev` on Atlas,
21 293 documents, 15 000 carrying an `ean`): **172 products** were emitted as
two rows whose only difference is a packaging word. Real pairs, before → after:

```
'170 GR' ATUN DESMENUZADO CUMANA AL NATURAL   mami          ┐
'170 g'  Atún al natural desmenuzado Cumana lata  carre     ┘ 1 row {carre, mami}

'500 GR' ARROZ GALLO PARBOIL X .              mami          ┐
'500 g'  Arroz Parboil Bolsa Gallo x .        hiper         ┘ 1 row {hiper, mami}

'500 cc' Aceite ... Arbequina Vidrio Oliovita  hiper         ┐
'500 cc' Aceite de oliva Oliovita arbequina   carre/chang/disco ┘ 1 row, 4 chains

'125 GR' ALMENDRAS CON CHOCOLATE LACASA DOYPACK  mami      ┐
'125 g'  Almendras Lacasa Con Chocolate Negro   chang     ┘ 1 row {chang, mami}
```

The owner's `ml` vs `cc` symptom is what those rows *read* like: the
Presentación column shows the winning document's `unidad`, so the same product
in the same size can display `500 ML` on one row and `500 cc` on the other.

The brand-variant class is **out of scope here** (`FAMILIA ZUCCARDI` vs
`Zuccardi`, `La Campagnola` vs `BC`); it is listed in §8 as a follow-up.

## 2. Decisions

- **D-25 · The unit question is closed by measurement, not by opinion.** No code
  changes for `ml`/`cc`: D-8 already normalizes them. Reported as verified.
- **D-26 · A packaging word is a *compatible-when-absent* attribute.** Same
  shape as D-9's brand rule: when one side names a container and the other names
  none, they are the same product; when **both** name one, they must agree.
  `vidrio` vs `pet` and `botella` vs `lata` therefore stay separate rows — those
  are different SKUs at the same size, not a spelling difference.
- **D-27 · Multipack and count words are not packaging.** `pack`, `caja`,
  `estuche`, `blister`, `display`, `un`, `unid` change *what is sold*, so they
  stay in the token set and keep their rows apart.
- **D-28 · The row id carries the packaging signature.** Two rows kept apart by
  D-26 must never hash to the same `id`, so `_layer2_key` appends the packaging
  signature when the row carries one. Row ids are computed per request and never
  persisted, so this only changes the ids of rows that name a container.
- **D-29 · A merge may drop a same-chain price — accepted by the owner.** `_row`
  keeps the first offer per chain (`matching.py:300`), so in the 52 groups where
  the same chain listed the product twice the merge loses one of those prices.
  The owner chose this over widening the payload (§Owner decision). Making
  `offers` a list per chain is the follow-up that removes the trade-off.
- **D-30 · Query-time only, no re-scrape** (same as D-24).

## 3. Owner decision

Asked with the measured impact (`ask_user_choice`, 2026-11-18), four options:
merge with the first chain price (A), merge and extend `offers` to a list (B),
merge only when chains do not collide (C), or document only (D).

**Owner chose A**: one row, first chain price wins.

## 4. Tasks

| # | Task | Evidence |
| --- | --- | --- |
| T1 | Feature document + tasks mirror | this file, Engram `odd/product-packaging-tokens/tasks` |
| T2 | RED: packaging compatibility tests | `pytest tests/test_matching.py` → 4 failed, 38 passed |
| T3 | GREEN: packaging attribute in `_Doc`/`_Group`/`_layer2_key` + absorb pass | `pytest tests/test_matching.py` → 42 passed · Atlas catalog 16 667 → 16 588 rows |
| T4 | Full suite + flake8 gate | 478 passed / 9 skipped · gate 0 |
| T5 | Live re-measure over `lalistitadev.productos` | §5 |
| T6 | Docs sync (`AGENTS.md`, `docs/agent-context/repo-map.md`) + close | this file |

## 5. Result (live catalog, 21 293 documents)

Read-only replay over `lalistitadev.productos` on Atlas — the database the app
reads through `.env` — with the old module and the new module loaded side by
side:

| | rows | single-chain rows | EAN rows | visible (row, chain) prices |
| --- | --- | --- | --- | --- |
| before | 16 667 | 13 703 | 2 867 | 21 250 |
| after | **16 588** | **13 584** | **2 885** | 21 244 |

- 79 fewer rows (−0.5 %) and 119 fewer rows showing a single chain.
- 302 document buckets merged a container-carrying group with its packless
  counterpart; 12 stayed apart because two containers conflict (D-26) and 3 kept
  D-2's fail-open behavior.
- **18 more EAN rows**: a container merge sometimes lets a layer-2 group land on
  the single EAN its key points at (D-20) instead of standing alone.
- **6 prices are hidden** by D-29 (the owner-accepted trade-off).
- 172 products were container-split before; 79 of them collapsed. The rest keep
  2+ container variants or an ambiguous EAN, both on purpose.
- No price is modified: matching only decides which documents share a row.
- No re-scrape needed (D-30).

An earlier run of this measurement used the **local** `mongod`
(17 112 documents, no `ean` at all, no ChangoMás): there the same change took
15 764 → 15 505 rows and hid 76 prices. The Atlas numbers above are the ones
that describe the product the owner sees, because `app.py` loads `.env`.

## 6. Verification

1. Tests first: 7 new tests in `tests/test_matching.py` (packaging on one side,
   two conflicting containers, container + different presentation, multipack is
   not packaging, container synonyms, fail-open with two containers and one
   packless row, container word is not an identity token). Observed RED —
   `4 failed, 38 passed` — then GREEN — `42 passed`.
2. Full `pytest`: **478 passed, 9 skipped** (the 9 are the opt-in MongoDB
   integration tests; no network, no DB, no Chrome in the suite).
3. `flake8 . --exclude .venv,adminpro,static,node_modules --select=E9,F63,F7,F82
   --count` → 0.
4. Read-only replay script over `lalistitadev.productos` for §5's counts and the
   Cocinero / Ybarra rows.
5. Frontend: no change needed, the payload shape is identical — only grouping.
   The owner's manual round is still the only UI evidence (AGENTS.md §8).

## 7. Residual risks

- **The owner's exact product keeps two rows for a different reason.**
  `Aceite de oliva Cocinero extra virgen` 500 exists under **two Carrefour
  `ean`s** (`7790070218216` packless and `7790070265098` pet). SuperMami's
  `500 ML` document has no `ean`, so it faces two candidate EANs and D-21's
  ambiguity guard keeps it on its own row. That is two real SKUs in Carrefour's
  catalogue, not a spelling difference; see §8.
- **Fail-open keeps 3 more cases split.** The packless row cannot choose between
  two containers: `Lira extra virgen` (no container) next to `Lira pet` and
  `Lira en botella`, and `Ketchup Dánica` next to `doypack` and `sachet`.
  Correct under D-2 — a guess corrupts the comparison.
- **12 conflict pairs stay split by design**: Oliovita `pet` vs `vidrio`,
  Carrefour Classic `botella`/`lata`/`pet`, Olivares del Neuquén `pet` vs
  `botella`, Bahía pulp `lata` vs `pet`, Sakura `botella` vs
  `botella de vidrio` (`cristal` is not in the map, so it stays a token).
- **`pet` vs `botella`** are distinct values: a chain writing one against a
  chain writing the other still splits even though both are plastic.
- **Display name** of a merged row can come from the container-naming document
  (`_display_name_offer` breaks ties by bucket order), so a row may read
  `... Cocinero extra virgen pet`. Cosmetic; the Presentación column is
  unaffected.
- **6 hidden prices** (D-29). The follow-up in §8 removes the trade-off.

## 8. Follow-ups (not in this branch)

- **Two `ean`s for the same product** (the real reason the owner's Cocinero 500
  still shows `500 ML` and `500 cc` as two rows). 315 identity keys carry 2+
  distinct EANs, 149 of them across different chains. Merging across distinct
  EANs contradicts layer 1 (an EAN is the strongest identity signal and two
  EANs are evidence of two SKUs), so it needs its own decision and its own
  measurement, not a silent extension of this branch.
- **Brand string variants** (37 groups, 74 rows on the local copy):
  `FAMILIA ZUCCARDI` vs `Zuccardi`, `La Campagnola` vs `BC`, `BON O BON` vs
  `BAGLEY`. Substring normalization risks merging two real brands.
- **`offers` as a list per chain** (D-29): removes the price loss entirely and
  would let the dashboard show both prices of the same chain.
