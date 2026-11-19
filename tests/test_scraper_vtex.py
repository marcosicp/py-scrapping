"""The shared VTEX price rule (P-1..P-3), one table of payload shapes.

``api/scrapers/vtex.py`` holds the one price rule the three VTEX scrapers
(changomas, carrefour, disco) call from their ``_price_of``. Each module used
to keep its own copy of ``items[0].sellers[0].commertialOffer.Price`` and the
three copies produced the same defect three times: 63 % of the ChangoMás
documents and 24 % of the Carrefour documents stored ``price = 0``, and
1 219 comparable rows showed a ``$0`` beside a real price from another chain
(odd/tasks/price-integrity.md).

Every case pins one payload shape that matters and the regression it stands
for. "No price" is asserted with ``is None`` — never ``0`` (P-1) — so a
regression back to the zero sentinel fails loudly.
"""
import pytest

from api.scrapers.vtex import price_of

# -- payload builders --------------------------------------------------------


def seller(price=None, available=None):
    """One seller; keys are omitted exactly as the live payloads omit them."""
    entry = {"sellerId": "1"}
    if price is not None or available is not None:
        offer = {}
        if price is not None:
            offer["Price"] = price
        if available is not None:
            offer["IsAvailable"] = available
        entry["commertialOffer"] = offer
    return entry


def item(*sellers):
    """One ``items[]`` entry with the given sellers, in payload order."""
    return {"itemId": "1", "sellers": list(sellers)}


def payload(*items):
    """One ``products/search`` item with the given ``items[]`` entries."""
    return {"productName": "Producto", "productId": 1, "items": list(items)}


# -- the rule, case by case --------------------------------------------------

CASES = [
    # -- the measured ChangoMás case: the first seller is an unavailable one
    # -- at Price 0.0 and the second carries the real price.
    ("first seller unavailable at 0.0, second available",
     payload(item(seller(0.0, False), seller(1519.0, True))), 1519.0),

    # -- a listed but out-of-stock price is still a real price (P-2).
    ("no available seller, one unavailable seller with a positive price",
     payload(item(seller(0.0, False), seller(800.0, False))), 800.0),
    ("single unavailable seller with a positive price",
     payload(item(seller(429.0, False))), 429.0),

    # -- IsAvailable absent counts as available, never as unavailable.
    ("IsAvailable absent counts as available",
     payload(item(seller(1519.0))), 1519.0),
    ("IsAvailable absent: an unusable 0 is skipped, the positive price wins",
     payload(item(seller(0.0), seller(900.0))), 900.0),

    # -- payload order decides: the first usable available seller wins.
    ("first available seller wins over a later cheaper one",
     payload(item(seller(1519.0, True), seller(999.0, True))), 1519.0),
]

UNUSABLE_PRICE_CASES = [
    ("Price as a string is never a price", payload(item(seller("1519")))),
    ("Price as a bool is never a price", payload(item(seller(True)))),
    ("Price as None is never a price",
     payload({"productName": "P", "productId": 1,
              "items": [item({"sellerId": "1",
                              "commertialOffer": {"Price": None}})]})),
    ("a missing Price key is never a price", payload(item(seller()))),
    ("a negative Price is never a price", payload(item(seller(-5.0)))),
    ("Price 0 is not a real price", payload(item(seller(0.0, True)))),
    ("every offer at Price 0 leaves no price",
     payload(item(seller(0.0, True), seller(0.0, False)))),
]

STRUCTURE_CASES = [
    ("no sellers at all", payload(item())),
    ("an items[] entry without a sellers key",
     payload({"itemId": "1"})),
    ("no items", payload()),
    ("no items key", {"productName": "P", "productId": 1}),
    ("items[0] not a dict", payload("not-a-dict")),
    ("a seller that is not a dict", payload(item(42))),
    ("a commertialOffer that is not a dict",
     payload({"itemId": "1", "sellers": [{"commertialOffer": "1519"}]})),
    # -- P-3: stay inside items[0]; items[1] is another SKU whose stored
    # -- identity is different (the stored ean is items[0].ean).
    ("a price in items[1] is never read",
     payload(item(), item(seller(500.0, True)))),
]


@pytest.mark.parametrize("name,product,expected", CASES, ids=[c[0] for c in CASES])
def test_the_rule_picks_the_measured_price(name, product, expected):
    assert price_of(product) == expected


@pytest.mark.parametrize("name,product", UNUSABLE_PRICE_CASES,
                         ids=[c[0] for c in UNUSABLE_PRICE_CASES])
def test_an_unusable_price_leaves_none_never_zero(name, product):
    price = price_of(product)
    assert price is None


@pytest.mark.parametrize("name,product", STRUCTURE_CASES,
                         ids=[c[0] for c in STRUCTURE_CASES])
def test_a_payload_without_a_usable_offer_leaves_none_never_zero(name, product):
    price = price_of(product)
    assert price is None
