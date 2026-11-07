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

- [ ] **T1 — reconcile EAN and layer-2 groups.** `api/services/matching.py`:
  merge a key group into its unique same-signature EAN group; keep ambiguous
  signatures separate. Test-first in `tests/test_matching.py`.
- [ ] **T2 — key chain lists by row id.** `adminpro/src/app/pages/dashboard/`:
  extract the toggle into a pure `selection.ts` module (id-keyed) and wire
  `dashboard.component.ts` to it. Verification without a browser: compile the
  module with the project `tsc` and run a Node assertion harness in `/tmp`
  (RED before, GREEN after) plus `npm run build`.
- [ ] **T3 — docs sync.** `docs/agent-context/repo-map.md` (grouping paragraph)
  and this document's evidence section.

## 4. Verification

See §6 below (filled as tasks close).

## 5. Out of scope

- Carrefour's 1 477 `price = 0.0` documents (separate follow-up).
- Presentation column in the chain lists (D-13).
- List persistence and the pre-existing checkbox/`data.selected` cosmetic
  desync recorded in `seleccion-smart.md` §7.
- Any browser-based verification (`AGENTS.md` §8 — the owner's manual round).
