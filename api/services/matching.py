"""Cross-supermarket product matching for the grouped view.

Builds the payload for the seleccion-smart feature (T2): one canonical row
per product with one offer per supermarket chain. Grouping is conservative
and query-time (no new dependencies, D-5):

* Layer 1 — exact EAN match (D-2): documents with the same non-empty ``ean``
  group together regardless of every other field.
* Layer 2 — canonical key for the rest: equal name token-set (lowercase,
  accents folded, punctuation split, Spanish stopwords dropped), presentation
  per D-8 and brand per D-9. Fail-open (D-2): a document missing brand or
  presentation family only joins a strict group when exactly one candidate
  group exists — with two or more candidates it stays ungrouped; a false
  positive would corrupt the price comparison, a false negative keeps
  today's behavior.
* Layer 1 / layer 2 reconciliation (D-11, refined by D-20): a layer-2 group
  joins the single EAN group that its own ``(tokens, qty, family)`` points at,
  brand compatible per D-9. Identity comes from the documents, never from
  whichever group member happened to arrive first.

The bucket mapping mirrors ``ProductService.catalog()``'s substring
convention and its five payload keys; documents from an unknown chain are
ignored altogether (D-3).

The service is pure: it consults no repository and touches no database.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import defaultdict
from typing import Any

# -- Payload keys, in catalog() order; Angular reads them as-is
_PAYLOAD_KEYS = ("carre", "disco", "mami", "hiper", "chang")
# -- Display tie-break contract (catalog() concatenation order); chang is
# appended last on purpose so no existing tie-break moves.
_BUCKET_ORDER = {"carre": 0, "disco": 1, "mami": 2, "hiper": 3, "chang": 4}

# -- Layer-2 Spanish stopwords excluded from the name token-set
_STOPWORDS = frozenset(
    {"de", "del", "la", "el", "los", "las", "con", "sin",
     "en", "x", "por", "para", "un", "una", "al"})

# -- D-8 unit families: unit -> (factor, base unit)
_UNIT_FAMILIES = {
    "kg": (1000.0, "g"), "kgs": (1000.0, "g"),
    "g": (1.0, "g"), "gr": (1.0, "g"), "grs": (1.0, "g"),
    "l": (1000.0, "ml"), "lt": (1000.0, "ml"), "lts": (1000.0, "ml"),
    "ml": (1.0, "ml"), "mls": (1.0, "ml"), "cc": (1.0, "ml"),
}
# -- longest variants first so ``kgs`` is never read as ``kg`` + stray ``s``
_UNITS = "|".join(sorted(_UNIT_FAMILIES, key=len, reverse=True))
_QTY_PATTERN = r"\d+(?:[.,]\d+)?"

# ``name_parse`` joins presentations with ", " ("1 kg, 500 ml"); the first
# quantity+unit wins. Pack quantities ("X2") have no D-8 rule and are
# deliberately left alone.
_UNIDAD_QTY_UNIT_RE = re.compile(
    rf"({_QTY_PATTERN})\s*({_UNITS})\b", re.IGNORECASE)
_QTY_TOKEN_RE = re.compile(rf"^{_QTY_PATTERN}$")
_UNIT_TOKEN_RE = re.compile(rf"^({_UNITS})$", re.IGNORECASE)
_FUSED_TOKEN_RE = re.compile(rf"^({_QTY_PATTERN})({_UNITS})$", re.IGNORECASE)


def _fold(text: str) -> str:
    """Lowercase and strip accents (NFKD, combining marks dropped)."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _bucket(supermercado: str) -> str | None:
    """Chain bucket for a document, or None when it must be ignored.

    Mirrors ``ProductService.catalog()``'s substring mapping (same elif
    order, first match wins; the ``hiper`` bucket carries La Anónima too,
    the ``chang`` bucket carries ChangoMás in both spellings:
    ``changomas`` and the accented ``changomás``).
    Deliberately duplicated here so matching does not import the catalog
    service and its repository port.
    """
    s = supermercado.lower()
    if "disco" in s:
        return "disco"
    if "carrefour" in s:
        return "carre"
    if ("hiperlibertad" in s or "hiper" in s
            or "anónima" in s or "anonima" in s):
        return "hiper"
    if "supermami" in s or "mami" in s:
        return "mami"
    # -- no existing key is a substring of "changomas", so this branch
    # cannot shadow the ones above
    if "changomas" in s or "changomás" in s:
        return "chang"
    return None


def _decimal_value(text: str) -> float:
    """Parse ``900`` / ``1.5`` / ``1,5`` (both separators) into a float."""
    return float(text.replace(",", "."))


def _brand_key(doc: dict[str, Any]) -> str | None:
    """Normalized brand for D-9, or None when the doc carries none."""
    raw = str(doc.get("brand", "") or "").strip()
    if not raw:
        return None
    return re.sub(r"\s+", " ", _fold(raw)).strip()


class _Doc:
    """One consumed document with its derived matching fields.

    ``qty``/``family`` are the normalized presentation (family None when the
    unit is missing or unresolvable), ``tokens`` the matching token-set with
    the presentation's quantity/unit already consumed, and ``consumed`` the
    folded strings that presentation search took out of the name.
    """

    __slots__ = ("doc", "bucket", "brand", "tokens", "qty", "family",
                 "consumed")

    def __init__(self, doc: dict[str, Any]) -> None:
        self.doc = doc
        self.bucket = _bucket(str(doc.get("supermercado", "")))
        self.brand: str | None = _brand_key(doc)
        raw_tokens = _fold(str(doc.get("name", ""))).split()
        self.consumed: set[str] = set()
        self.qty, self.family = self._presentation(
            str(doc.get("unidad", "") or ""), raw_tokens)
        self.tokens = self._name_tokens(raw_tokens)

    # -- presentation per D-8 ------------------------------------------

    def _consume(self, *tokens: str) -> None:
        """Register presentation strings taken out of the name, with pieces.

        ``_name_tokens`` splits on ``[^0-9a-z]+``, so a consumed ``"1.5"``
        survives as ``"1"`` and ``"5"`` unless its pieces are consumed too
        (C3): two documents of the same product then disagree on the token
        set and never group.
        """
        for token in tokens:
            self.consumed.add(token)
            self.consumed.update(
                piece for piece in re.split(r"[^0-9a-z]+", token) if piece)

    def _presentation(
            self, unidad: str, name_tokens: list[str]) -> tuple[Any, Any]:
        """Quantity and unit family from ``unidad``, else from the name.

        Returns ``(quantity, family)`` where family is None when the unit is
        missing (bare number in the name) or not in the D-8 maps; both are
        None when there is no presentation at all.
        """
        match = _UNIDAD_QTY_UNIT_RE.search(_fold(unidad))
        if match:
            qty_text, unit = match.group(1).lower(), match.group(2).lower()
            self._consume(qty_text, unit, qty_text + unit)
            factor, family = _UNIT_FAMILIES[unit]
            return _decimal_value(match.group(1)) * factor, family
        for i, tok in enumerate(name_tokens):
            fused = _FUSED_TOKEN_RE.match(tok)
            if fused:
                factor, family = _UNIT_FAMILIES[fused.group(2).lower()]
                self._consume(tok.lower())
                return _decimal_value(fused.group(1)) * factor, family
            if (_QTY_TOKEN_RE.match(tok) and i + 1 < len(name_tokens)
                    and _UNIT_TOKEN_RE.match(name_tokens[i + 1])):
                factor, family = _UNIT_FAMILIES[name_tokens[i + 1].lower()]
                self._consume(tok.lower(), name_tokens[i + 1].lower())
                return _decimal_value(tok) * factor, family
        # -- no unit anywhere: the first bare number is the presentation
        for tok in name_tokens:
            if _QTY_TOKEN_RE.match(tok):
                self._consume(tok.lower())
                return _decimal_value(tok), None
        return None, None

    def _name_tokens(self, raw_tokens: list[str]) -> tuple[str, ...]:
        """Matching token-set: punctuation split, stopwords and the
        presentation's quantity/unit dropped, sorted."""
        pieces = []
        for tok in raw_tokens:
            for piece in re.split(r"[^0-9a-z]+", tok):
                if (piece and piece not in _STOPWORDS
                        and piece not in self.consumed):
                    pieces.append(piece)
        return tuple(sorted(pieces))


def _append(groups: dict, key: Any, doc: _Doc) -> None:
    """Index ``doc`` under ``key``: the first document defines the group."""
    group = groups.get(key)
    if group is None:
        groups[key] = _Group(doc)
    else:
        group.members.append(doc)


class _Group:
    """A candidate canonical group: its winning key parts plus members."""

    __slots__ = ("tokens", "qty", "family", "brand", "members")

    def __init__(self, doc: _Doc) -> None:
        self.tokens = doc.tokens
        self.qty = doc.qty
        self.family = doc.family
        self.brand = doc.brand
        self.members: list[_Doc] = [doc]


def _is_strict(group: _Group) -> bool:
    """A strict group carries brand AND presentation family (D-9, D-8)."""
    return (group.brand is not None and group.family is not None
            and group.qty is not None)


def _joins_strict(loose: _Group, strict: _Group) -> bool:
    """Whether ``loose`` may join ``strict``: equal tokens and quantity,
    families equal or missing on one side (D-8), brands equal when both
    sides carry one (D-9)."""
    if loose.tokens != strict.tokens:
        return False
    if loose.qty != strict.qty:
        return False
    if (loose.family is not None and strict.family is not None
            and loose.family != strict.family):
        return False
    return not (loose.brand is not None and strict.brand is not None
                and loose.brand != strict.brand)


def _layer2_key(group: _Group) -> str:
    """Canonical layer-2 winning key (§3): tokens|quantity|family|brand."""
    tokens, qty, family, brand = group.tokens, group.qty, group.family, group.brand
    return (f"key:{' '.join(tokens)}|"
            f"{'' if qty is None else format(qty, 'g')}|"
            f"{family or ''}|{brand or ''}")


def _match_label(member_count: int, kind: str) -> str:
    """``ean``/``key`` only when the group actually joined documents."""
    return kind if member_count > 1 else "solo"


def _display_name_offer(members: list[_Doc]) -> _Doc:
    """Offer with the most information: brand+unidad beats either alone
    beats neither; ties go to bucket order carre→disco→mami→hiper→chang."""
    best = members[0]
    best_rank = (-_score(best), _BUCKET_ORDER[best.bucket])
    for doc in members[1:]:
        rank = (-_score(doc), _BUCKET_ORDER[doc.bucket])
        if rank < best_rank:
            best, best_rank = doc, rank
    return best


def _score(doc: _Doc) -> int:
    """Information score: truthy brand plus truthy unidad (0..2)."""
    return int(bool(doc.doc.get("brand"))) + int(bool(doc.doc.get("unidad")))


def _row(group: _Group, winning_key: str, match: str) -> dict[str, Any]:
    """§3 payload row for one canonical group."""
    offers: dict[str, dict[str, Any]] = {}
    for doc in group.members:
        if doc.bucket not in offers:  # first offer per chain wins
            offers[doc.bucket] = {
                "name": doc.doc.get("name", ""),
                "price": doc.doc.get("price"),
            }
    offer = _display_name_offer(group.members)
    return {
        "id": hashlib.sha1(winning_key.encode("utf-8")).hexdigest()[:16],
        "name": offer.doc.get("name", ""),
        "unidad": offer.doc.get("unidad", ""),
        "brand": offer.doc.get("brand", ""),
        "offers": offers,
        "match": match,
    }


def group_products(docs: list[dict]) -> dict:
    """Group product documents into canonical rows with per-chain offers.

    Takes repository-shaped documents (``supermercado``, ``name``,
    ``unidad``, ``brand``, ``price``, optional ``ean`` — a missing ``ean``
    key counts as absent). Returns the §3 payload: one row per canonical
    product with the winning-key id like ``sha1[:16]`` of ``ean:<ean>`` or
    ``key:<tokens>|<qty>|<family>|<brand>``, per-chain offers, and one
    consumed-document count per chain bucket (D-3: unknown origins ignored).
    """
    counts = dict.fromkeys(_PAYLOAD_KEYS, 0)
    ean_groups: dict[str, _Group] = {}
    key_groups: dict[tuple, _Group] = {}

    for doc in docs:
        if not isinstance(doc, dict):
            continue
        item = _Doc(doc)
        if item.bucket is None:
            continue  # unknown origin (D-3)
        counts[item.bucket] += 1
        ean = str(doc.get("ean", "") or "").strip()
        if ean:
            _append(ean_groups, ean, item)
        else:
            _append(key_groups, (item.tokens, item.qty, item.family,
                                 item.brand), item)

    # -- D-2 ambiguity guard: a group without brand or presentation family
    # joins a strict group only when exactly one candidate exists, and only
    # strict groups (brand + family + quantity present) may receive it.
    strict = [g for g in key_groups.values() if _is_strict(g)]
    loose = [g for g in key_groups.values() if not _is_strict(g)]
    by_signature = defaultdict(list)
    for group in strict:
        by_signature[(group.tokens, group.qty)].append(group)
    absorbed = set()
    for group in sorted(loose, key=_layer2_key):  # deterministic pass
        candidates = [
            strict_g for strict_g in by_signature[(group.tokens, group.qty)]
            if _joins_strict(group, strict_g)]
        if len(candidates) == 1:
            candidates[0].members.extend(group.members)
            absorbed.add(id(group))

    # -- Layer 1 / layer 2 reconciliation (D-11, refined by D-20): only Disco
    # and Carrefour persist ``ean`` (seleccion-smart T1), so one physical
    # product reaches layer 1 through them and layer 2 through the other
    # chains. A layer-2 group joins the EAN group that its own
    # (tokens, qty, family) points at, but only when exactly one EAN matches
    # and the brands are compatible the D-9 way: equal when BOTH sides carry
    # one, no requirement when one side carries none. Anything ambiguous stays
    # on its own row, the same fail-open bias as D-2.
    #
    # The index is built from every EAN-backed DOCUMENT, not from a group's
    # first member: ``_Group`` copies its key parts from whichever document
    # arrived first, and on live data 2 270 of the 2 644 multi-document EAN
    # groups have members whose tokens/qty/family disagree, so a group-level
    # comparison made the merge depend on insertion order (C2).
    eans_by_key: dict[tuple, set[str]] = defaultdict(set)
    brands_by_ean: dict[str, set[str]] = defaultdict(set)
    for ean, group in ean_groups.items():
        for member in group.members:
            if member.qty is not None and member.family is not None:
                eans_by_key[(member.tokens, member.qty,
                             member.family)].add(ean)
            if member.brand is not None:
                brands_by_ean[ean].add(member.brand)
    for group in key_groups.values():
        if id(group) in absorbed:
            continue
        if group.qty is None or group.family is None:
            continue  # nothing corroborates the promotion (D-21)
        candidates = eans_by_key.get((group.tokens, group.qty, group.family))
        if not candidates or len(candidates) != 1:
            continue  # unknown or ambiguous: stay on its own row
        ean = next(iter(candidates))
        if (group.brand is not None and brands_by_ean[ean]
                and group.brand not in brands_by_ean[ean]):
            continue  # D-9: two known, different brands never merge
        ean_groups[ean].members.extend(group.members)
        absorbed.add(id(group))

    rows = []
    for ean, group in ean_groups.items():
        rows.append(_row(group, f"ean:{ean}", _match_label(
            len(group.members), "ean")))
    for group in key_groups.values():
        if id(group) in absorbed:
            continue  # its members live in the strict group now
        rows.append(_row(group, _layer2_key(group), _match_label(
            len(group.members), "key")))

    rows.sort(key=lambda row: (row["name"], row["id"]))
    return {"productos": rows, **counts}
