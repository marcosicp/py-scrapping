"""The VTEX price rule shared by changomas, carrefour and disco (P-4).

Until 2026-11 each of the three VTEX scrapers kept its own copy of the same
three lines, ``items[0].sellers[0].commertialOffer.Price``, and both halves of
that expression were wrong:

1. ``sellers[0]`` was read without checking ``IsAvailable``. VTEX lists
   several sellers per SKU and the first one can be an unavailable seller
   carrying ``Price: 0.0`` while a later seller carries the real price —
   the measured case: a stored ``Ketchup Danica`` sat at ``$0`` while the
   API answered ``$1.519`` available.
2. ``0`` was the "unknown" value, so an unavailable SKU and a genuine zero
   were indistinguishable downstream and both rendered as ``$0`` — a lie
   where the product answers "where is it cheaper".

The measurement behind this module (odd/tasks/price-integrity.md, read-only
probes against the deployed database and the live API): 63 % of the
ChangoMás documents and 24 % of the Carrefour documents stored
``price = 0``, and 1 219 comparable rows showed a ``$0`` beside a real
price from another chain. In a random sample of 40 zero-price documents per
chain, 7 of 40 ChangoMás prices were recoverable — all of them in
``items[0]``, from a later seller — and 0 of 80 documents needed a
different ``items[k]``.

The rule (P-1..P-3): stay inside ``items[0]`` — the stored ``ean`` is
``items[0].ean``, so another SKU's price would attach a price to the wrong
identity; walk the sellers of that item in payload order; prefer the first
seller whose ``commertialOffer.IsAvailable`` is not ``False`` and whose
``Price`` is a real positive number; if none is available, take the first
seller with a positive numeric ``Price`` (a listed but out-of-stock price is
still a real price); otherwise return ``None`` — never ``0`` (P-1).
"""

from __future__ import annotations


def _usable_price(value) -> bool:
    """A real positive price: numeric, not a bool, not a string, above 0."""
    return (isinstance(value, (int, float))
            and not isinstance(value, bool)
            and value > 0)


def price_of(item: dict):
    """The price to store for one ``products/search`` item, or None."""
    items = item.get("items") if isinstance(item, dict) else None
    if not items or not isinstance(items[0], dict):
        return None

    # -- stay inside items[0]: the stored ean is items[0].ean (P-3).
    first = items[0]

    fallback_price = None
    for seller in first.get("sellers") or []:
        if not isinstance(seller, dict):
            continue
        offer = seller.get("commertialOffer")
        if not isinstance(offer, dict):
            continue
        price = offer.get("Price")
        if not _usable_price(price):
            continue
        # -- IsAvailable absent counts as available: only an explicit
        # -- False means the offer is listed but out of stock.
        if offer.get("IsAvailable") is not False:
            return price
        if fallback_price is None:
            fallback_price = price
    return fallback_price
