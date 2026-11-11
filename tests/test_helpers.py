"""``name_parse`` / ``remove_duplicates_by_key`` behavior.

``name_parse`` decides the stored ``name``/``unidad`` of every scraper, so its
edges are contract, not trivia. The decimal cases below are the ones that used
to corrupt real product names (`... pet 1.5 lts` became `... pet 1.` with
`unidad: "5 lts"`), found by the native review of the Carrefour scraper
(R3-002).
"""
import pytest

from api.helpers import name_parse, remove_duplicates_by_key


def test_removes_the_first_quantity_and_returns_it_as_the_unit():
    assert name_parse("Yerba Playadito 1 kg") == {
        "name": "Yerba Playadito", "unidad": "1 kg"}


def test_decimal_point_is_kept_whole():
    """The pattern used to match `5 lts` inside `1.5 lts` and mangle the name."""
    assert name_parse("Aceite de girasol pet 1.5 lts") == {
        "name": "Aceite de girasol pet", "unidad": "1.5 lts"}


def test_decimal_comma_is_kept_whole():
    assert name_parse("Gaseosa 1,5 lts") == {
        "name": "Gaseosa", "unidad": "1,5 lts"}


@pytest.mark.parametrize("text", [
    "Atún al Natural x 160 g.",
    "Mayonesa 500 ml",
    "Cerveza 1 lt",
    "Agua 2 lts",
    "Pack X2 900 cc",
])
def test_recognised_units_are_unchanged(text):
    parsed = name_parse(text)
    assert parsed["unidad"], f"no unit found in {text!r}"
    assert parsed["unidad"] not in parsed["name"]


def test_bare_litre_is_recognised():
    """`l` was missing from the unit set (only `lt`/`lts` were there), so 102
    catalog names kept an empty `unidad` and matching had to recover the
    presentation from the name — C3 in
    `odd/tasks/catalog-matching-normalization.md`."""
    assert name_parse("Aceite Girasol Pureza 1.5 L") == {
        "name": "Aceite Girasol Pureza", "unidad": "1.5 L"}


def test_trailing_period_after_the_unit_is_handled():
    # -- the unit is read even with the site's trailing period. The dangling
    # punctuation it leaves in `name` is pre-existing behavior for every
    # `... 160 g.` style name and out of scope here (follow-up in the feature
    # document), so this pins the unit side only.
    parsed = name_parse("Vinagre de alcohol Favinco pet 1 l.")
    assert parsed["unidad"] == "1 l"
    assert "1 l" not in parsed["name"]


def test_bare_m_keeps_its_baseline_behavior():
    # -- `m` stays in the unit set on purpose: matching cannot resolve it as a
    # unit family, but removing it changed how metre-length names are stored,
    # which is out of scope for this fix (review R3-001).
    assert name_parse("Cinta adhesiva 50 m") == {
        "name": "Cinta adhesiva", "unidad": "50 m"}


def test_multiple_quantities_are_comma_joined_but_only_the_first_is_removed():
    """Legacy behavior: the unit list is complete, the name loses one match."""
    parsed = name_parse("Pack 3 x 200 ml")
    assert parsed["unidad"] == "200 ml"


def test_a_name_without_a_quantity_is_returned_untouched():
    assert name_parse("Pan de campo") == {"name": "Pan de campo", "unidad": ""}


def test_remove_duplicates_by_key_keeps_the_first_occurrence():
    rows = [{"name": "a", "price": 1}, {"name": "a", "price": 2},
            {"name": "b", "price": 3}]
    assert remove_duplicates_by_key(rows, "name") == [
        {"name": "a", "price": 1}, {"name": "b", "price": 3}]
