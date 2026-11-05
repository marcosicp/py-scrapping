"""Unit tests for the cross-supermarket matching service — T2.

Pins the seleccion-smart contract (§3) at the service layer: layer-1 EAN
grouping, layer-2 conservative canonical-key grouping (D-2 fail-open, D-8
presentation, D-9 brand rule), the grouped payload shape, per-bucket counts
and deterministic ordering. Pure tests: no network, no DB, no Chrome.
"""

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


def test_ean_doc_never_joins_layer2_group():
    # -- an EAN-bearing doc only groups through layer 1; a same-name doc
    # without EAN stays ungrouped (D-2 fail-open).
    payload = group_products([
        _doc(supermercado="carrefour", ean="7790272001005"),
        _doc(supermercado="hiperlibertad", name="Aceite de girasol natura",
             unidad="900 cc", brand=""),
    ])
    assert len(payload["productos"]) == 2
    assert all(p["match"] == "solo" for p in payload["productos"])


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


# -- Output contract (§3) --------------------------------------------------


def test_solo_docs_appear_with_single_offer():
    payload = group_products([
        _doc(supermercado="supermami", name="Detergente Ala",
             unidad="750 ml", brand="Ala", price=900),
    ])
    row = payload["productos"][0]
    assert set(row) == {"id", "name", "unidad", "brand", "offers", "match"}
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
    assert set(payload) == {"productos", "carre", "disco", "mami", "hiper"}
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


def test_changomas_ignored_out_of_scope():
    payload = group_products([
        _doc(supermercado="disco", name="Yerba", ean="123"),
        _doc(supermercado="ChangoMas", name="Yerba", ean="123"),
    ])
    assert payload["disco"] == 1
    assert payload["carre"] == 0
    assert payload["mami"] == 0
    assert payload["hiper"] == 0
    assert payload["productos"][0]["offers"] == {
        "disco": {"name": "Yerba", "price": 1500}}


def test_empty_input():
    assert group_products([]) == {
        "productos": [], "carre": 0, "disco": 0, "mami": 0, "hiper": 0}
