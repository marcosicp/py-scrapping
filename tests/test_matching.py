"""Unit tests for the cross-supermarket matching service — T2.

Pins the seleccion-smart contract (§3) at the service layer: layer-1 EAN
grouping, layer-2 conservative canonical-key grouping (D-2 fail-open, D-8
presentation, D-9 brand rule), the grouped payload shape, per-bucket counts
and deterministic ordering. Pure tests: no network, no DB, no Chrome.
"""

import hashlib
from itertools import permutations

from api.services.matching import group_products


def _doc(**overrides):
    """A plausible repository document; every field can be overridden."""
    doc = {
        "supermercado": "disco",
        "name": "Aceite de girasol Natura 900 cc",
        "unidad": "900 cc",
        "brand": "Natura",
        "price": 1500,
        "ean": "",
    }
    doc.update(overrides)
    return doc


# -- Layer 1: EAN ----------------------------------------------------------


def test_ean_groups_across_chains_regardless_of_other_fields():
    payload = group_products([
        _doc(supermercado="carrefour", ean="7790272001005"),
        _doc(supermercado="disco", name="Girasol natura", unidad="900 ml",
             ean="7790272001005"),
    ])
    assert len(payload["productos"]) == 1
    row = payload["productos"][0]
    assert row["match"] == "ean"
    assert set(row["offers"]) == {"carre", "disco"}
    # -- EAN wins even when token sets would differ
    assert row["offers"]["carre"]["price"] == 1500


def test_ean_group_and_solo_counts():
    payload = group_products([
        _doc(supermercado="carrefour", ean="7790272001005",
             name="Completamente distinto", brand="Otra marca"),
        _doc(supermercado="supermami", ean="7790272001005"),
        _doc(supermercado="hiperlibertad", ean="1", name="Solo"),
    ])
    assert payload["carre"] == 1
    assert payload["mami"] == 1
    assert payload["hiper"] == 1
    assert payload["disco"] == 0
    assert len(payload["productos"]) == 2  # ean pair + hiperlibertad solo
    ean_rows = [p for p in payload["productos"] if p["match"] == "ean"]
    assert len(ean_rows) == 1
    assert set(ean_rows[0]["offers"]) == {"carre", "mami"}


def test_single_doc_with_ean_is_solo():
    payload = group_products([_doc(ean="7790272001005")])
    assert len(payload["productos"]) == 1
    assert payload["productos"][0]["match"] == "solo"


def test_ean_document_keeps_its_identity_when_a_brandless_doc_joins():
    # -- D-20 retired the old assertion here (a brandless same-name document
    # used to stay ungrouped, which is the bug the owner reported on
    # 2026-11-10). What still holds: layer 1 owns the row identity and the EAN
    # label, and a document that does not match is never pulled in.
    payload = group_products([
        _doc(supermercado="carrefour", ean="7790272001005"),
        _doc(supermercado="hiperlibertad", name="Aceite de girasol natura",
             unidad="900 cc", brand=""),
        _doc(supermercado="supermami", name="Aceite de girasol natura",
             unidad="1.5 lt", brand=""),
    ])
    assert len(payload["productos"]) == 2
    ean_row = [p for p in payload["productos"] if p["match"] == "ean"][0]
    assert ean_row["id"] == _hashed("ean:7790272001005")
    assert set(ean_row["offers"]) == {"carre", "hiper"}
    solo = [p for p in payload["productos"] if p["match"] != "ean"][0]
    assert set(solo["offers"]) == {"mami"}


# -- Layer 2: tokens, presentation, brand ----------------------------------


def test_token_set_matches_across_word_order_and_stopwords():
    payload = group_products([
        _doc(supermercado="carrefour", name="Aceite de Girasol Natura",
             unidad="", price=100),
        _doc(supermercado="disco", name="aceite girasol natura",
             unidad="", price=95),
    ])
    assert len(payload["productos"]) == 1
    row = payload["productos"][0]
    assert row["match"] == "key"
    assert set(row["offers"]) == {"carre", "disco"}
    assert row["offers"]["carre"]["price"] == 100


def test_unit_variants_match():
    # -- 900 cc ≡ 900 ml (same family)
    payload = group_products([
        _doc(supermercado="carrefour", name="Aceite girasol", unidad="900 cc"),
        _doc(supermercado="disco", name="Aceite girasol", unidad="900 ml"),
    ])
    assert len(payload["productos"]) == 1
    assert payload["productos"][0]["match"] == "key"
    # -- 1 kg ≡ 1000 g (same normalized quantity and family)
    payload = group_products([
        _doc(supermercado="carrefour", name="Yerba playadito", unidad="1 kg"),
        _doc(supermercado="disco", name="Yerba playadito", unidad="1000 g"),
    ])
    assert len(payload["productos"]) == 1
    assert payload["productos"][0]["match"] == "key"


def test_bare_number_matches_unitful_presentation():
    # -- no unidad: "Natura 900" resolves a unit-less (900, family None)
    # presentation that must match (900 ml) via D-8's missing-family rule.
    payload = group_products([
        _doc(supermercado="carrefour", name="Natura 900", unidad=""),
        _doc(supermercado="disco", name="Natura 900 cc", unidad=""),
    ])
    assert len(payload["productos"]) == 1
    assert payload["productos"][0]["match"] == "key"


def test_brandless_doc_joins_unique_strict_group():
    payload = group_products([
        _doc(supermercado="carrefour", name="Aceite de girasol natura 900 cc"),
        _doc(supermercado="hiperlibertad", name="Aceite de girasol natura 900",
             unidad="", brand=""),
    ])
    assert len(payload["productos"]) == 1
    row = payload["productos"][0]
    assert row["match"] == "key"
    # -- display comes from the offer with brand+unidad
    assert row["brand"] == "Natura"
    assert set(row["offers"]) == {"carre", "hiper"}


def test_different_brands_do_not_match():
    payload = group_products([
        _doc(supermercado="carrefour", name="Aceite de girasol", brand="Natura"),
        _doc(supermercado="disco", name="Aceite de girasol", brand="Arcor"),
    ])
    assert len(payload["productos"]) == 2
    assert all(p["match"] == "solo" for p in payload["productos"])


def test_different_presentation_does_not_match():
    payload = group_products([
        _doc(supermercado="carrefour", name="Aceite de girasol",
             unidad="900 cc"),
        _doc(supermercado="disco", name="Aceite de girasol", unidad="1,5 l"),
    ])
    assert len(payload["productos"]) == 2
    assert all(p["match"] == "solo" for p in payload["productos"])


def test_weight_family_vs_volume_family_does_not_match():
    payload = group_products([
        _doc(supermercado="carrefour", name="Sal fina 500", unidad="500 g"),
        _doc(supermercado="disco", name="Sal fina 500", unidad="500 ml"),
    ])
    assert len(payload["productos"]) == 2


def test_missing_presentation_does_not_match_unitful():
    payload = group_products([
        _doc(supermercado="carrefour", name="Aceite de girasol natura",
             unidad=""),
        _doc(supermercado="disco", name="Aceite de girasol natura",
             unidad="900 cc"),
    ])
    assert len(payload["productos"]) == 2
    assert all(p["match"] == "solo" for p in payload["productos"])


def test_extra_meaningful_token_does_not_match():
    payload = group_products([
        _doc(supermercado="carrefour", name="Yerba Playadito", unidad=""),
        _doc(supermercado="disco", name="Yerba Playadito Orgánica", unidad=""),
    ])
    assert len(payload["productos"]) == 2
    assert all(p["match"] == "solo" for p in payload["productos"])


def test_ambiguity_guard_two_strict_groups_brandless_stays_separate():
    # -- two brand-distinct strict groups with equal tokens+presentation:
    # the brandless doc has two candidates and stays ungrouped (D-2).
    payload = group_products([
        _doc(supermercado="carrefour", name="Aceite de girasol natura 900 cc",
             brand="Natura"),
        _doc(supermercado="disco", name="Aceite de girasol natura 900 cc",
             brand="Arcor"),
        _doc(supermercado="hiperlibertad", name="Aceite de girasol natura 900",
             unidad="", brand=""),
    ])
    assert len(payload["productos"]) == 3
    assert all(p["match"] == "solo" for p in payload["productos"])
    assert all(len(p["offers"]) == 1 for p in payload["productos"])
    assert {frozenset(p["offers"]) for p in payload["productos"]} == {
        frozenset(["carre"]), frozenset(["disco"]), frozenset(["hiper"])}


# -- Row categoria (C-3): derived from the member documents ---------------


def test_row_categoria_takes_the_most_frequent_member_slug():
    payload = group_products([
        _doc(supermercado="carrefour", ean="1", categoria="almacen"),
        _doc(supermercado="disco", ean="1", categoria="almacen"),
        _doc(supermercado="supermami", ean="1", categoria="bebidas"),
    ])
    row = payload["productos"][0]
    assert row["categoria"] == "almacen"


def test_row_categoria_tie_breaks_alphabetically_lowest_wins():
    payload = group_products([
        _doc(supermercado="carrefour", ean="1", categoria="bebidas"),
        _doc(supermercado="disco", ean="1", categoria="almacen"),
    ])
    assert payload["productos"][0]["categoria"] == "almacen"


def test_row_categoria_none_when_no_member_carries_one():
    payload = group_products([_doc()])
    assert payload["productos"][0]["categoria"] is None


def test_row_categoria_ignores_whitespace_only_values():
    payload = group_products([
        _doc(supermercado="carrefour", ean="1", categoria="  "),
        _doc(supermercado="disco", ean="1", categoria=""),
    ])
    assert payload["productos"][0]["categoria"] is None


def test_row_categoria_is_the_last_key_of_the_row():
    payload = group_products([_doc(categoria="almacen")])
    row = payload["productos"][0]
    assert list(row.keys())[-1] == "categoria"


def test_row_categoria_existing_keys_and_values_unchanged():
    """Purely additive: the pre-categoria row for the same documents keeps
    every key and value it had before."""
    docs = [
        _doc(supermercado="carrefour", ean="1"),
        _doc(supermercado="disco", ean="1", categoria="almacen"),
    ]
    row = group_products(docs)["productos"][0]
    assert set(row) == {"id", "name", "unidad", "brand", "offers",
                        "match", "categoria"}
    assert row["categoria"] == "almacen"


# -- include_member_categories (comparator-focus F-2) -----------------------
# Off by default: the API payload must stay byte-identical — ``categorias``
# is the coverage instrument's field, not the dashboard's.


def test_rows_do_not_carry_categorias_by_default():
    row = group_products([_doc(categoria="almacen")])["productos"][0]
    assert "categorias" not in row
    assert list(row.keys())[-1] == "categoria"


def test_explicit_false_is_the_same_payload_as_the_default():
    docs = [_doc(supermercado="carrefour", ean="1", categoria="almacen"),
            _doc(supermercado="disco", ean="1")]
    assert (group_products(docs)["productos"]
            == group_products(
                docs, include_member_categories=False)["productos"])


def test_categorias_is_the_sorted_deduplicated_member_categories():
    row = group_products([
        _doc(supermercado="carrefour", ean="1", categoria="almacen"),
        _doc(supermercado="disco", ean="1",
             categoria="desayuno-y-merienda"),
        _doc(supermercado="supermami", ean="1", categoria="almacen"),
    ], include_member_categories=True)["productos"][0]
    assert row["categorias"] == ["almacen", "desayuno-y-merienda"]


def test_categorias_is_empty_when_no_member_carries_one():
    row = group_products([_doc()],
                         include_member_categories=True)["productos"][0]
    assert row["categorias"] == []


def test_categorias_ignores_blank_values():
    row = group_products([
        _doc(supermercado="carrefour", ean="1", categoria="  "),
        _doc(supermercado="disco", ean="1", categoria=""),
    ], include_member_categories=True)["productos"][0]
    assert row["categorias"] == []


def test_categorias_counts_absorbed_members():
    # -- a loose layer-2 document joins a strict group: its slug must land in
    # the receiver row's ``categorias`` too, or coverage would undercount it.
    row = group_products([
        _doc(supermercado="carrefour",
             name="Aceite de girasol natura 900 cc", brand="Natura"),
        _doc(supermercado="hiperlibertad",
             name="Aceite de girasol natura 900", unidad="", brand="",
             categoria="almacen"),
    ], include_member_categories=True)["productos"][0]
    assert row["match"] == "key"
    assert row["categoria"] == "almacen"
    assert row["categorias"] == ["almacen"]


def test_categorias_is_the_last_key_when_on():
    row = group_products([_doc(categoria="almacen")],
                         include_member_categories=True)["productos"][0]
    assert list(row.keys())[-1] == "categorias"


# -- Output contract (§3) --------------------------------------------------


def test_solo_docs_appear_with_single_offer():
    payload = group_products([
        _doc(supermercado="supermami", name="Detergente Ala",
             unidad="750 ml", brand="Ala", price=900),
    ])
    row = payload["productos"][0]
    assert set(row) == {"id", "name", "unidad", "brand", "offers",
                        "match", "categoria"}
    assert row["name"] == "Detergente Ala"
    assert row["unidad"] == "750 ml"
    assert row["brand"] == "Ala"
    assert row["offers"] == {"mami": {"name": "Detergente Ala", "price": 900}}
    assert row["match"] == "solo"
    assert payload["mami"] == 1
    assert payload["carre"] == 0
    assert payload["disco"] == 0
    assert payload["hiper"] == 0


def test_payload_shape_and_stable_id():
    payload = group_products([_doc(), _doc(supermercado="carrefour")])
    assert set(payload) == {
        "productos", "carre", "disco", "mami", "hiper", "chang"}
    row = payload["productos"][0]
    assert len(row["id"]) == 16
    int(row["id"], 16)  # lowercase hex sha1 prefix
    again = group_products([_doc(supermercado="carrefour"), _doc()])
    assert again["productos"][0]["id"] == row["id"]


def test_display_offer_most_information_then_bucket_order():
    payload = group_products([
        _doc(supermercado="disco", name="Aceite girasol natura 900",
             unidad="", brand="Natura"),  # only brand
        _doc(supermercado="carrefour", name="Aceite girasol natura",
             unidad="900 ml", brand="Natura"),  # brand + unidad wins
    ])
    row = payload["productos"][0]
    assert row["name"] == "Aceite girasol natura"
    assert row["unidad"] == "900 ml"
    assert row["brand"] == "Natura"

    payload = group_products([
        _doc(supermercado="disco", name="Zeta", unidad="1 l", brand="Z"),
        _doc(supermercado="carrefour", name="Zeta la", unidad="1 lt",
             brand="Z"),
    ])
    assert payload["productos"][0]["name"] == "Zeta la"  # carre first on ties


def test_deterministic_ordering_by_name_then_id():
    docs = [
        _doc(supermercado="disco", name="Yerba", unidad=""),
        _doc(supermercado="carrefour", name="Azúcar", unidad="1 kg",
             brand="A"),
        _doc(supermercado="supermami", name="azucar", unidad="1 kg",
             brand="a"),
        _doc(supermercado="carrefour", name="Beta", unidad="", brand="B"),
    ]
    payload = group_products(docs)
    names = [p["name"] for p in payload["productos"]]
    assert names == ["Azúcar", "Beta", "Yerba"]  # sorted, grouping pinned
    reordered = group_products(list(reversed(docs)))
    assert [p["id"] for p in reordered["productos"]] == [
        p["id"] for p in payload["productos"]]


def test_missing_ean_key_treated_as_empty():
    missing = _doc(supermercado="carrefour")
    del missing["ean"]
    explicit = _doc(supermercado="disco")
    payload = group_products([missing, explicit])
    assert len(payload["productos"]) == 1
    assert payload["productos"][0]["match"] == "key"
    assert set(payload["productos"][0]["offers"]) == {"carre", "disco"}


def test_changomas_documents_get_their_own_chang_bucket():
    payload = group_products([
        _doc(supermercado="disco", name="Yerba", ean="123"),
        _doc(supermercado="ChangoMas", name="Yerba", ean="123"),
    ])
    assert len(payload["productos"]) == 1
    assert payload["disco"] == 1
    assert payload["chang"] == 1
    assert payload["carre"] == 0
    assert payload["mami"] == 0
    assert payload["hiper"] == 0
    assert payload["productos"][0]["offers"] == {
        "disco": {"name": "Yerba", "price": 1500},
        "chang": {"name": "Yerba", "price": 1500}}


def test_chang_bucket_accepts_every_spelling():
    payload = group_products([
        _doc(supermercado="ChangoMas", name="Yerba A"),
        _doc(supermercado="ChangoMás", name="Yerba B"),
        _doc(supermercado="CHANGOMAS", name="Yerba C"),
    ])
    assert payload["chang"] == 3
    assert payload["disco"] == 0
    assert payload["carre"] == 0
    assert payload["mami"] == 0
    assert payload["hiper"] == 0
    # -- every spelling lands in the same bucket, each product its own row
    assert len(payload["productos"]) == 3
    assert all(set(row["offers"]) == {"chang"}
               for row in payload["productos"])
    assert {row["offers"]["chang"]["name"]
            for row in payload["productos"]} == {"Yerba A", "Yerba B", "Yerba C"}


def test_empty_input():
    assert group_products([]) == {
        "productos": [], "carre": 0, "disco": 0, "mami": 0, "hiper": 0,
        "chang": 0}


# -- Layer 1 / layer 2 reconciliation (D-11, D-12) -------------------------
#
# Only Disco and Carrefour persist ``ean`` (seleccion-smart T1), so the same
# physical product reaches layer 1 through those chains and layer 2 through
# SuperMami / La Anónima. Without reconciliation it is emitted as two rows and
# the UI can only fill half of its per-chain lists.


def _hashed(key: str) -> str:
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def test_ean_group_absorbs_the_same_product_without_ean():
    payload = group_products([
        _doc(supermercado="carrefour", name="Aceite de girasol Cañuelas",
             unidad="900 cc", brand="Cañuelas", price=4399,
             ean="7792180001641"),
        _doc(supermercado="disco", name="Aceite De Girasol Cañuelas",
             unidad="900 cc", brand="Cañuelas", price=4700,
             ean="7792180001641"),
        _doc(supermercado="supermami", name="ACEITE DE GIRASOL CAÑUELAS X .",
             unidad="900 ML", brand="CAÑUELAS", price=3269.0),
        _doc(supermercado="la anónima", name="Aceite de Girasol Cañuelas x .",
             unidad="900 ML", brand="", price=4500),
    ])
    assert len(payload["productos"]) == 1
    row = payload["productos"][0]
    # -- D-12: the merged row keeps the EAN identity and label
    assert row["match"] == "ean"
    assert row["id"] == _hashed("ean:7792180001641")
    assert set(row["offers"]) == {"carre", "disco", "mami", "hiper"}
    assert {chain: offer["price"] for chain, offer in row["offers"].items()} == {
        "carre": 4399, "disco": 4700, "mami": 3269.0, "hiper": 4500}
    # -- counts stay consumed-document counts, not row counts
    assert (payload["carre"], payload["disco"],
            payload["mami"], payload["hiper"]) == (1, 1, 1, 1)


def test_decimal_presentation_left_in_the_name_does_not_split_the_row():
    # -- C3 of `odd/tasks/catalog-matching-normalization.md`: two layers of
    # token normalization disagreed. `_presentation` consumes the raw name
    # token ("1.5") while `_name_tokens` splits on `[^0-9a-z]+`, so the leaked
    # pieces were "1" and "5" and the same product ended up with two token
    # sets — exactly the Disco / La Anónima pair of the owner's report.
    payload = group_products([
        _doc(supermercado="disco", name="Aceite Girasol Pureza 1.5 L",
             unidad="", brand="PUREZA", ean=""),
        _doc(supermercado="la anónima", name="Aceite de Girasol Pureza x .",
             unidad="1,5 Lt", brand=""),
    ])
    assert len(payload["productos"]) == 1
    assert set(payload["productos"][0]["offers"]) == {"disco", "hiper"}


def test_a_number_elsewhere_in_the_name_survives_the_presentation():
    # -- H-1 of the review (2026-11-11): `consumed` was a set of STRINGS, so the
    # pieces of `1.5` ("1" and "5") deleted every standalone `1`/`5` in the
    # name and two different packs collapsed into one row — the false positive
    # the whole module is supposed to avoid.
    payload = group_products([
        _doc(supermercado="disco", name="Yogur firme 1 unidad 1.5 L",
             unidad="", brand="", ean=""),
        _doc(supermercado="la anónima", name="Yogur firme 5 unidad 1.5 L",
             unidad="", brand="", ean=""),
    ])
    assert len(payload["productos"]) == 2
    # -- and the same pack still merges, so the guard is not "numbers block"
    payload = group_products([
        _doc(supermercado="disco", name="Yogur firme 5 unidad 1.5 L",
             unidad="", brand="", ean=""),
        _doc(supermercado="la anónima", name="Yogur firme 5 unidad 1,5 Lt",
             unidad="", brand="", ean=""),
    ])
    assert len(payload["productos"]) == 1


def test_numbers_that_belong_to_the_name_are_not_consumed():
    # -- R3-003: the two documents differ ONLY by the number in the name, so
    # they can only merge if that number is dropped from the token set. The
    # previous version of this test gave both documents the same number, so it
    # would have passed even with a regression that eats name numbers.
    apart = group_products([
        _doc(supermercado="carrefour", name="Aceite de oliva 120 Años",
             unidad="500 cc", brand="", ean=""),
        _doc(supermercado="disco", name="Aceite de oliva 200 Años",
             unidad="500 ml", brand="", ean=""),
    ])
    assert len(apart["productos"]) == 2
    assert all(row["match"] == "solo" for row in apart["productos"])
    # -- and the same number on both sides still merges, so the guard is not
    # just "numbers always block"
    together = group_products([
        _doc(supermercado="carrefour", name="Aceite de oliva 120 Años",
             unidad="500 cc", brand="", ean=""),
        _doc(supermercado="disco", name="Aceite de oliva 120 Años",
             unidad="500 ml", brand="", ean=""),
    ])
    assert len(together["productos"]) == 1


def test_a_contradictory_unit_in_the_name_is_not_consumed():
    # -- R3-002 of the native review: the presentation taken from `unidad`
    # dropped whatever unit token followed the repeated quantity, even when it
    # named a different family. That deleted the only token telling a document
    # spelled `1.5 kg` apart from one spelled `1.5 L`, so two contradictory
    # listings collapsed into one row — a false positive, which is the failure
    # this module exists to avoid.
    payload = group_products([
        _doc(supermercado="disco", name="Aceite firme 1.5 kg",
             unidad="1,5 Lt", brand="", ean=""),
        _doc(supermercado="la anónima", name="Aceite firme 1.5 L",
             unidad="1,5 Lt", brand="", ean=""),
    ])
    assert len(payload["productos"]) == 2


def test_a_same_family_unit_in_the_name_is_still_consumed():
    # -- the other side of R3-002: the repeated presentation is still dropped
    # when it names the same family, which is the case the fix exists for.
    payload = group_products([
        _doc(supermercado="disco", name="Aceite firme 1.5 L",
             unidad="1,5 Lt", brand="", ean=""),
        _doc(supermercado="la anónima", name="Aceite firme 1,5 Lt",
             unidad="", brand="", ean=""),
    ])
    assert len(payload["productos"]) == 1


def test_ambiguous_ean_signature_keeps_the_layer2_group_separate():
    # -- two EAN groups share the canonical signature: the third document has
    # two candidates and stays on its own row (D-11 fail-open).
    payload = group_products([
        _doc(supermercado="carrefour", name="Aceite de girasol Natura 900 cc",
             unidad="900 cc", brand="Natura", ean="111"),
        _doc(supermercado="disco", name="Aceite de girasol Natura 900 ml",
             unidad="900 ml", brand="Natura", ean="222"),
        _doc(supermercado="supermami", name="ACEITE GIRASOL NATURA X 900",
             unidad="", brand="NATURA"),
    ])
    assert len(payload["productos"]) == 3
    assert sorted(row["match"] for row in payload["productos"]) == [
        "solo", "solo", "solo"]
    assert {frozenset(row["offers"]) for row in payload["productos"]} == {
        frozenset(["carre"]), frozenset(["disco"]), frozenset(["mami"])}


def test_ean_group_with_a_different_presentation_is_not_absorbed():
    payload = group_products([
        _doc(supermercado="carrefour", name="Aceite de girasol Natura 900 cc",
             unidad="900 cc", brand="Natura", ean="111"),
        _doc(supermercado="supermami", name="ACEITE GIRASOL NATURA X 1500",
             unidad="1.5 LT", brand="NATURA"),
    ])
    assert len(payload["productos"]) == 2
    assert all(row["match"] == "solo" for row in payload["productos"])


def test_brandless_document_joins_the_single_matching_ean_group():
    # -- the owner's report (2026-11-10): "aceite girasol pureza" in `1,5 lt`
    # (La Anónima) and `1500 cc` (Carrefour) rendered as two rows. La Anónima
    # stores no brand at all, and D-20 promotes a brandless document by its own
    # (tokens, qty, family) key instead of demanding signature equality (D-9
    # only requires equal brands when BOTH sides carry one).
    payload = group_products([
        _doc(supermercado="carrefour", name="Aceite de girasol Pureza",
             unidad="1500 cc", brand="Pureza", price=7465,
             ean="7792180137944"),
        _doc(supermercado="disco", name="Aceite Girasol Pureza 1.5 L",
             unidad="", brand="PUREZA", price=7850, ean="7792180137944"),
        _doc(supermercado="changomas", name="Aceite De Girasol Pureza 1.5 L",
             unidad="", brand="Pureza", price=7469, ean="7792180137944"),
        _doc(supermercado="la anónima", name="Aceite de Girasol Pureza x .",
             unidad="1,5 Lt", brand="", price=7900),
    ])
    assert len(payload["productos"]) == 1
    row = payload["productos"][0]
    assert row["match"] == "ean"
    assert row["id"] == _hashed("ean:7792180137944")
    assert set(row["offers"]) == {"carre", "disco", "chang", "hiper"}
    assert row["offers"]["hiper"]["price"] == 7900


def test_brandless_join_does_not_depend_on_insertion_order():
    # -- R3-004: the EAN group must have TWO members that disagree on their
    # derived fields, because that is the shape that made the old group-level
    # signature depend on which document arrived first (Carrefour `1500 cc`
    # against Disco `1.5 L` with an empty `unidad`). A single EAN document
    # would not exercise it. Both orders must return the same payload.
    ean = "7792180137944"
    carre = _doc(supermercado="carrefour", name="Aceite de girasol Pureza",
                 unidad="1500 cc", brand="Pureza", price=7465, ean=ean)
    disco = _doc(supermercado="disco", name="Aceite Girasol Pureza 1.5 L",
                 unidad="", brand="PUREZA", price=7850, ean=ean)
    anonima = _doc(supermercado="la anónima",
                   name="Aceite de Girasol Pureza x .", unidad="1,5 Lt",
                   brand="", price=7900)
    forward = group_products([carre, disco, anonima])["productos"]
    backward = group_products([anonima, disco, carre])["productos"]
    assert len(forward) == 1
    assert forward == backward
    assert set(forward[0]["offers"]) == {"carre", "disco", "hiper"}
    assert forward[0]["id"] == _hashed(f"ean:{ean}")
    # -- every arrival order, not just the two obvious ones
    orders = list(permutations([carre, disco, anonima]))
    payloads = [group_products(list(order))["productos"] for order in orders]
    assert all(payload == payloads[0] for payload in payloads), \
        f"{len(orders)} orders, {len({str(p) for p in payloads})} payloads"


def test_a_conflicting_brand_keeps_the_document_separate():
    # -- D-9 survives D-20: when both sides carry a brand and they differ, the
    # document stays on its own row even though (tokens, qty, family) match.
    payload = group_products([
        _doc(supermercado="carrefour", name="Aceite de girasol 900 cc",
             unidad="900 cc", brand="Pureza", ean="111"),
        _doc(supermercado="supermami", name="Aceite de girasol 900 cc",
             unidad="900 cc", brand="Natura"),
    ])
    assert len(payload["productos"]) == 2
    assert all(row["match"] == "solo" for row in payload["productos"])


def test_unresolved_presentation_never_joins_an_ean_group():
    # -- D-21: without a resolved quantity and family there is nothing to
    # corroborate the promotion, so the document keeps its own row.
    payload = group_products([
        _doc(supermercado="carrefour", name="Aceite de girasol Pureza",
             unidad="900 cc", brand="Pureza", ean="111"),
        _doc(supermercado="la anónima", name="Aceite de girasol Pureza x .",
             unidad="", brand=""),
    ])
    assert len(payload["productos"]) == 2
    assert all(row["match"] == "solo" for row in payload["productos"])


def test_promotion_requires_exactly_one_candidate_ean():
    # -- the fail-open bias of D-2/D-21 is preserved: two EAN groups share the
    # key, so the brandless document has two candidates and stays apart.
    payload = group_products([
        _doc(supermercado="carrefour", name="Aceite de girasol Pureza 900 cc",
             unidad="900 cc", brand="Pureza", ean="111"),
        _doc(supermercado="disco", name="Aceite de girasol Pureza 900 ml",
             unidad="900 ml", brand="Pureza", ean="222"),
        _doc(supermercado="la anónima", name="Aceite de girasol Pureza 900 cc",
             unidad="900 cc", brand=""),
    ])
    assert len(payload["productos"]) == 3
    assert all(row["match"] == "solo" for row in payload["productos"])


# -- Packaging words (D-26, D-27, D-28) ------------------------------------
#
# Only some chains name the container in the product name. A packaging word is
# a *compatible-when-absent* attribute, the same shape as D-9's brand rule: one
# side naming a container and the other naming none is the same product, while
# two different containers at the same size are two real products.


def test_packaging_word_on_one_side_does_not_split_the_row():
    # -- owner report 2026-11-18 ("aceite oliva extra virgen": 250 Ml vs
    # 250 cc). Disco names no container, Carrefour says "pet", La Anónima
    # carries no brand.
    payload = group_products([
        _doc(supermercado="disco",
             name="Aceite De Oliva Cocinero Extra Virgen", unidad="X250 cc",
             brand="COCINERO", price=8500),
        _doc(supermercado="carrefour",
             name="Aceite de oliva Cocinero extra virgen pet", unidad="250 cc",
             brand="Cocinero", price=7900),
        _doc(supermercado="la anónima",
             name="Aceite de Oliva Extra Virgen Pet Cocinero x .",
             unidad="250 cc", brand="", price=8100),
    ])
    assert len(payload["productos"]) == 1
    row = payload["productos"][0]
    assert row["match"] == "key"
    assert set(row["offers"]) == {"disco", "carre", "hiper"}
    assert row["offers"]["carre"]["price"] == 7900


def test_two_different_containers_at_the_same_size_stay_split():
    # -- Carrefour lists the same oil "en botella" and "en lata": two SKUs of
    # the same size, so D-26 keeps them apart and D-28 keeps their ids apart.
    payload = group_products([
        _doc(supermercado="carrefour",
             name="Aceite de oliva Carrefour Classic virgen en botella",
             unidad="500 ml", brand="Carrefour", price=100),
        _doc(supermercado="carrefour",
             name="Aceite de oliva virgen Carrefour Classic en lata",
             unidad="500 ml", brand="Carrefour", price=120),
    ])
    assert len(payload["productos"]) == 2
    assert all(row["match"] == "solo" for row in payload["productos"])
    assert len({row["id"] for row in payload["productos"]}) == 2


def test_packaging_word_does_not_join_a_different_presentation():
    payload = group_products([
        _doc(supermercado="carrefour", name="Aceite de oliva Lira pet",
             unidad="500 cc", brand="Lira"),
        _doc(supermercado="disco", name="Aceite de oliva Lira", unidad="250 ml",
             brand="Lira"),
    ])
    assert len(payload["productos"]) == 2


def test_multipack_and_count_words_are_not_packaging():
    # -- D-27: a pack changes what is sold, so it stays in the token set. The
    # names differ ONLY by that word on purpose (review R3-002): a leftover
    # number would keep the pair apart on its own and hide the regression that
    # moved `pack`/`caja` into the container map.
    payload = group_products([
        _doc(supermercado="carrefour", name="Yerba Playadito Pack",
             unidad="1 kg", brand="Playadito"),
        _doc(supermercado="disco", name="Yerba Playadito", unidad="1000 g",
             brand="Playadito"),
        _doc(supermercado="supermami", name="Gelatina Royal Caja",
             unidad="25 g", brand="Royal"),
        _doc(supermercado="hiperlibertad", name="Gelatina Royal", unidad="25 g",
             brand=""),
    ])
    # -- yerba pair and gelatina pair each keep their two rows: the pack is a
    # token of its own, never a compatible-when-absent attribute
    assert len(payload["productos"]) == 4


def test_packaging_synonyms_are_the_same_container():
    # -- "bot" and "botella" name the same bottle, so the pair joins even
    # though both sides carry a container word.
    payload = group_products([
        _doc(supermercado="disco", name="Aceite De Oliva Pisi Bot .",
             unidad="250 cc", brand="PISI"),
        _doc(supermercado="carrefour", name="Aceite de Oliva Pisi botella",
             unidad="250 ml", brand="Pisi"),
    ])
    assert len(payload["productos"]) == 1
    assert payload["productos"][0]["match"] == "key"


def test_two_containers_keep_a_packless_row_separate():
    # -- D-2's fail-open bias still rules: with two container candidates the
    # packless document has no unique counterpart and stays on its own row.
    payload = group_products([
        _doc(supermercado="carrefour", name="Aceite de oliva Lira pet",
             unidad="500 cc", brand="Lira"),
        _doc(supermercado="disco", name="Aceite de oliva Lira lata",
             unidad="500 cc", brand="Lira"),
        _doc(supermercado="hiperlibertad", name="Aceite de oliva Lira",
             unidad="500 cc", brand="Lira"),
    ])
    assert len(payload["productos"]) == 3
    assert all(row["match"] == "solo" for row in payload["productos"])


def test_two_brandless_containers_do_not_collapse_into_one_row():
    # -- review R3-001: a branded row that names no container is the single D-2
    # receiver of two BRANDLESS container variants, and the brand pass used to
    # accept both of them, putting `lata` and `botella` in the same row.
    payload = group_products([
        _doc(supermercado="carrefour", name="Aceite de oliva Lira",
             unidad="500 cc", brand="Lira", price=1500),
        _doc(supermercado="hiperlibertad", name="Aceite de oliva Lira lata",
             unidad="500 cc", brand="", price=1400),
        _doc(supermercado="supermami", name="Aceite de oliva Lira botella",
             unidad="500 ML", brand="", price=1600),
    ])
    assert len(payload["productos"]) == 3
    assert all(row["match"] == "solo" for row in payload["productos"])
    assert all(len(row["offers"]) == 1 for row in payload["productos"])


def test_one_brandless_container_still_joins_the_packless_row():
    # -- the other half of R3-001: with a single container candidate the merge
    # D-26 promises must still happen.
    payload = group_products([
        _doc(supermercado="carrefour", name="Aceite de oliva Lira",
             unidad="500 cc", brand="Lira", price=1500),
        _doc(supermercado="hiperlibertad", name="Aceite de oliva Lira lata",
             unidad="500 cc", brand="", price=1400),
    ])
    assert len(payload["productos"]) == 1
    row = payload["productos"][0]
    assert set(row["offers"]) == {"carre", "hiper"}
    assert row["offers"]["hiper"]["price"] == 1400


def test_packaging_word_is_not_a_token_of_the_row():
    # -- a container word must not survive as identity: "Oliovita" spelled
    # with "vidrio" and without it is the same product.
    payload = group_products([
        _doc(supermercado="la anónima",
             name="Aceite de Oliva Extra Virgen Vidrio Lira x .",
             unidad="500 cc", brand=""),
        _doc(supermercado="supermami", name="ACEITE DE OLIVA LIRA EXTRA VIRGEN",
             unidad="500 ML", brand="LIRA"),
    ])
    assert len(payload["productos"]) == 1
    assert set(payload["productos"][0]["offers"]) == {"hiper", "mami"}


def test_a_brandless_container_competes_with_a_branded_one():
    # -- second-round review R3-001: the container pass used to compare brands
    # for exact equality, so it saw only the same-brand `lata` variant and
    # glued the packless row to it, even though the BRANDLESS `pet` row is an
    # equally valid candidate under D-9. The packless row is ambiguous and must
    # stay on its own row.
    payload = group_products([
        _doc(supermercado="carrefour", name="Aceite de oliva Lira",
             unidad="500 cc", brand="Lira", price=1500),
        _doc(supermercado="disco", name="Aceite de oliva Lira lata",
             unidad="500 cc", brand="Lira", price=1400),
        _doc(supermercado="hiperlibertad", name="Aceite de oliva Lira pet",
             unidad="500 cc", brand="", price=1600),
    ])
    assert len(payload["productos"]) == 3
    assert all(row["match"] == "solo" for row in payload["productos"])
    assert all(len(row["offers"]) == 1 for row in payload["productos"])


def test_a_shared_container_still_merges_branded_and_brandless():
    # -- the other side of the same rule: when every candidate carries the SAME
    # container the brandless document still joins (D-9), so the Cocinero pair
    # the owner reported keeps one row.
    payload = group_products([
        _doc(supermercado="disco", name="Aceite de Oliva Cocinero Extra Virgen",
             unidad="X250 cc", brand="COCINERO", price=8500),
        _doc(supermercado="carrefour",
             name="Aceite de oliva Cocinero extra virgen pet", unidad="250 cc",
             brand="Cocinero", price=7900),
        _doc(supermercado="la anónima",
             name="Aceite de Oliva Extra Virgen Pet Cocinero x .",
             unidad="250 cc", brand="", price=8100),
    ])
    assert len(payload["productos"]) == 1
    assert set(payload["productos"][0]["offers"]) == {"disco", "carre", "hiper"}


def test_a_contested_group_is_never_absorbed():
    # -- third-round review R3-001: the ambiguity verdict was applied when a
    # container arrives (join into a contested receiver) but NOT to the
    # contested group itself, so a brandless packless row — ambiguous between
    # two containers — still joined the branded container row through the
    # brand pass and collapsed two products.
    payload = group_products([
        _doc(supermercado="supermami", name="Aceite de oliva Lira",
             unidad="500 ML", brand="", price=1600),
        _doc(supermercado="carrefour", name="Aceite de oliva Lira lata",
             unidad="500 cc", brand="Lira", price=1500),
        _doc(supermercado="hiperlibertad", name="Aceite de oliva Lira pet",
             unidad="500 cc", brand="", price=1400),
    ])
    assert len(payload["productos"]) == 3
    assert all(row["match"] == "solo" for row in payload["productos"])


def test_a_contested_group_still_merges_when_one_container_remains():
    # -- the guard must not freeze a row that is not ambiguous: with a single
    # container in play the brandless packless document still joins it.
    payload = group_products([
        _doc(supermercado="supermami", name="Aceite de oliva Lira",
             unidad="500 ML", brand="", price=1600),
        _doc(supermercado="carrefour", name="Aceite de oliva Lira lata",
             unidad="500 cc", brand="Lira", price=1500),
        _doc(supermercado="hiperlibertad", name="Aceite de oliva Lira en lata",
             unidad="500 cc", brand="", price=1400),
    ])
    assert len(payload["productos"]) == 1
    assert set(payload["productos"][0]["offers"]) == {"mami", "carre", "hiper"}
