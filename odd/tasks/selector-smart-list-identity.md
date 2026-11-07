# Selector smart — chain list identity and EAN/key reconciliation

**Branch:** `fix/selector-smart-list-identity` (from `main`)
**Status:** in progress. Owner reported the defect; scope chosen by the owner:
both defects (A + B), no presentation column in the chain lists.

Requested by the owner: *"detecté un bug, el selector smart de productos del
sitio no funciona bien. Lo detecté filtrando por 'aceite girasol cañu' y agregué
productos y vi que no se agregan correctamente a las listas."*

---

## 1. Investigation (read-only evidence, live data)

Data read from `lalistitadev.productos` (17 194 documents, read-only) and
`matching.group_products()` replayed locally. No browser round was run
(`AGENTS.md` §8: the owner owns that round).

### Defect A — chain lists key on `offer.name` (`dashboard.component.ts:229-241`)

`addRemoveOffer` adds only when `item.name !== offer.name` and removes **every**
entry whose `name` matches. A chain can reach two canonical rows through the
same offer name, so the second selection is silently dropped and one deselection
wipes unrelated rows. SuperMami stores all three Cañuelas presentations as
`"ACEITE DE GIRASOL CAÑUELAS X ."`; La Anónima stores both of its as
`"Aceite de Girasol Cañuelas x ."`.

Replay of the owner's filter (`aceite girasol cañu` → 7 canonical rows, all
selected):

| chain | entries added | entries expected |
| --- | --- | --- |
| Carrefour | 3 | 4 |
| Disco | 2 | 2 |
| SuperMami | 1 | 3 |
| La Anónima | 1 | 2 |

Deselecting one of the SuperMami rows then emptied **both** SuperMami (3 → 0)
and La Anónima (1 → 0) while the other rows stayed checked.

Catalog-wide: **1 121 `(chain, offer name)` pairs map to 2+ canonical rows, and
2 266 of 15 595 rows are affected.**

### Defect B — EAN groups and layer-2 groups never reconcile (`matching.py:275-317`)

A document is appended to `ean_groups` *or* `key_groups`, and the two families
are emitted as separate rows. Only Disco and Carrefour persist `ean` (T1 of
`seleccion-smart.md`), so a product carried by the four chains appears as two
rows — one with the EAN-backed offers, one with the rest — and selecting one row
fills only half the lists.

Live example, the row pair behind the owner's filter:

```
ean | Aceite de girasol Cañuelas | 900 cc | offers: carre 4399, disco 4700
key | ACEITE DE GIRASOL CAÑUELAS X . | 900 ML | offers: mami 3269, hiper 4500
```

Catalog-wide: **284 key groups have exactly one EAN group with the same
canonical signature** (tokens, quantity, family, brand) and merge cleanly;
7 signatures have 2+ EAN candidates and stay separate under the D-2 fail-open
rule. Total documents moved: 288; row count 15 595 → 15 311.

### Reported separately, out of scope

**1 477 Carrefour documents carry `price = 0.0`** → `$0` list lines and
understated totals. A scraper defect (its own follow-up), not a selector defect.

## 2. Decisions

- **D-10 — list identity is the canonical row id, not the offer name.** Each
  chain list entry carries `{id, name, price}` and is added/removed by `id`.
  Rationale: `id` is already the stable canonical key the API emits, and it is
  unique per row by construction (`sha1[:16]` of the winning key). Two offers
  with the same display name are two different presentations and must both be
  selectable.
- **D-11 — reconciliation is exact-signature and unique-candidate only.** A key
  group joins an EAN group only when `(tokens, qty, family, brand)` are equal
  and exactly one EAN candidate exists. Anything else stays separate: a false
  positive corrupts the price comparison, a false negative keeps today's
  behavior (the same fail-open bias as D-2). Loose-vs-loose still never merges.
- **D-12 — the merged row keeps the EAN identity.** `id` stays
  `sha1[:16]("ean:<ean>")` and `match` becomes `ean`, so the row identity the
  frontend already uses does not move.
- **D-13 — no presentation column in the chain lists** (owner scope: A + B).
  Two same-name entries stay distinguishable by price and by their master-grid
  `Presentación` column; adding the column is a separate UX decision.

## 3. Tasks

- [x] **T1 — reconcile EAN and layer-2 groups.** DONE in `80a6b67`
  (`fix(services): reconcile ean and layer-2 groups for the same product`).
- [x] **T2 — key chain lists by row id.** DONE in `20d2e1e`
  (`fix(ui): key chain list selection by canonical row id`).
- [x] **T3 — docs sync.** `docs/agent-context/repo-map.md` (grouping
  paragraph), `AGENTS.md` + `docs/agent-context/runbook.md` (suite count
  401 → 405) and this document's evidence section.

## 4. Verification

See §6 below.

## 5. Out of scope

- Carrefour's 1 477 `price = 0.0` documents (separate follow-up).
- Presentation column in the chain lists (D-13).
- List persistence and the pre-existing checkbox/`data.selected` cosmetic
  desync recorded in `seleccion-smart.md` §7.
- Any browser-based verification (`AGENTS.md` §8 — the owner's manual round).

---

## 6. Verification evidence

**T1 — `80a6b67`** — four new tests in `tests/test_matching.py`, RED first
(`assert 2 == 1` on the four-chain Cañuelas case), GREEN after the
reconciliation pass: suite **405 passed / 9 skipped**, flake8 CI gate **0**.
The other three new tests (ambiguous signature, different presentation,
loose-vs-strict) pass before the change too — they pin the fail-open behavior
the fix must not weaken. Live replay over `lalistitadev.productos` (17 194
documents): rows **15 595 → 15 311**, 288 documents absorbed, the owner's
filter now returns **5 rows** instead of 7 and both Cañuelas oils carry all
four offers:

```
ean | Aceite de girasol Cañuelas | 900 cc   | carre 4399  disco 4700  mami 3269  hiper 4500
ean | Aceite de girasol Cañuelas | 1.5 lts  | carre 6985  disco 7450  mami 5299  hiper 7650
solo | ACEITE DE GIRASOL CAÑUELAS X . | 5 LT  | mami 17500
solo | Aceite en aerosol Cañuelas de girasol | 187 cc | carre 4399
solo | Aceite mezcla Cañuelas girasol y oliva 15 l |   | carre 0.0  (the $0 defect)
```

**T2 — `20d2e1e`** — `selection.ts` (Angular-free, id-keyed) plus the
component wiring; `addRemoveOffer` is gone. Browser-free verification because
`adminpro` has zero specs and karma would need Chrome (`AGENTS.md` §8):

```
npx tsc src/app/pages/dashboard/selection.ts --outDir /tmp/selcheck \
  --module es2022 --target es2022 --strict --skipLibCheck
node /tmp/verify_selection.mjs
```

RED before the module existed (`ERR_MODULE_NOT_FOUND`), RED with the legacy
name-keyed logic copied verbatim (`AssertionError: both presentations must
reach the list — 1 !== 2`), GREEN after the fix (`selection logic OK`). The
harness also pins no-double-add, deselect-one-keeps-sibling,
deselect-absent-id, and the `{id, name, price}` entry shape. `npm run build`
green (8.8 s, chunk `main-THIXW7Z5.js`, only the two pre-existing stylesheet
warnings); `static/` stays gitignored.

**What the owner's round has to confirm** (agent-side verification stops
before the browser): `./dev.sh` or `python app.py`, open `/` → dashboard,
filter `aceite girasol cañu`, tick all five rows, and expect
**Carrefour 4 · Disco 2 · SuperMami 3 · La Anónima 2** entries; untick only
the 900 ML row and expect SuperMami 2 / La Anónima 1 remaining.

**Native review — lineage `review-cf61d65d3205f0ee`** — candidate
`main..HEAD` (8 files / 382 changed lines incl. this document), tier
**medium**, one lens `review-reliability`. START created it directly (no
consent envelope was returned). The capture forecast one host-relayed model
run and it ran: **approved**, one advisory WARNING, no correction offered,
no finding blocked. Authority burned (`gentle-ai.review-acknowledged/v1`,
revision `sha256:d42f6209…`). The advisory is recorded as a follow-up below;
delivery (push, PR, merge) stays an owner decision.

## 7. Follow-ups

- **Review advisory `R3-SELECTION-TEST`** (WARNING, informational,
  `selection.ts:35-53`): the toggle has no test inside the repository — the
  Node harness that proved RED→GREEN lives in `/tmp` by design, because
  `adminpro` has no spec runner that avoids Chrome. Committing a repo-side
  check would need a documented non-browser TS test entry point.
- **Carrefour `price = 0.0` on 1 477 documents** (2026-11-07), 1477 of 6187,
  samples: `Vinagre de alcohol San Ignacio botella`, `Aceite de oliva extra
  virgen Malagueña botella`. Produces `$0` list lines and understated totals.
  Scraper defect, its own task.
- **Presentation in the chain lists (D-13)**: with id-keyed entries two
  same-name offers are correct but visually ambiguous. Deferred by the owner.
- **Checkbox/`data.selected` cosmetic desync** inherited from
  `seleccion-smart.md` §7, unchanged by this fix.
