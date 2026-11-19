"""EAN enrichment loop (ean-enrichment T3): the engine, without the seams.

A pure walk over candidate documents that fills the missing barcodes of one
chain. It holds no HTTP library, no database and no Flask import: the site
knowledge (``url_for``, ``extract_ean``), the transport (``fetch``), the
reporter and the pause are all injected, so a second chain later means two
functions, not an edit here (N-2).

The loop is idempotent and resumable by construction (N-3): only documents
with a truthy ``sku`` and an empty ``ean`` are candidates, an existing ``ean``
is never overwritten, and a product whose page carries no barcode is counted,
not dumped into an error.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

# The pause the loop suggests between two detail-page requests. The caller's
# injected ``sleep`` receives it and may honour its own value instead (the
# CLI's ``--sleep`` overrides it, ean-enrichment N-5).
PAUSE_SECONDS = 0.4


@dataclass(frozen=True)
class EnrichmentReport:
    """The counters of one enrichment walk."""

    attempted: int
    enriched: int
    without_gtin: int
    failed: int


def enrich_eans(
    documents: Iterable[Mapping],
    *,
    url_for: Callable[[str], str],
    extract_ean: Callable[[str], str | None],
    fetch: Callable[[str], str],
    report: Callable[[str], None],
    sleep: Callable[[float], None] | None = None,
) -> tuple[dict[str, str], EnrichmentReport]:
    """Fetch the missing barcodes of ``documents`` and return the mapping.

    ``documents`` are mapping-like product documents; only those with a
    truthy ``sku`` and an empty ``ean`` are attempted (N-3), and a repeated
    ``sku`` is attempted once — the result is one mapping entry per product,
    never the same detail page requested twice. ``url_for(sku)`` builds the
    detail URL, ``extract_ean(text)`` pulls the barcode out of the page (or
    returns ``None``), and ``fetch(url)`` returns the page text — it may
    raise, which counts that product as ``failed`` together with a
    non-string body, both reported through ``report`` without stopping the
    walk.

    ``sleep`` is an optional pause between two requests, so tests never
    sleep; it runs after every request except the last one.

    Returns ``(mapping_of_sku_to_ean, report)``; the caller persists the
    mapping through the repository's ``update_eans`` (N-4).
    """
    # -- candidates: empty-ean documents with an identity, one per sku.
    candidates: list[tuple[str, Mapping]] = []
    seen: set[str] = set()
    for document in documents:
        sku = document.get("sku")
        if not sku or document.get("ean"):
            continue
        if sku in seen:
            continue
        seen.add(sku)
        candidates.append((sku, document))

    mapping: dict[str, str] = {}
    attempted = enriched = without_gtin = failed = 0
    for position, (sku, _document) in enumerate(candidates):
        if position > 0 and sleep is not None:
            sleep(PAUSE_SECONDS)
        attempted += 1
        url = url_for(sku)
        try:
            body = fetch(url)
        except Exception as exc:
            failed += 1
            report(f"Error de red en {url}: {exc}")
            continue
        if not isinstance(body, str):
            failed += 1
            report(f"Respuesta no textual en {url}")
            continue
        ean = extract_ean(body)
        if not ean:
            without_gtin += 1
            continue
        mapping[sku] = ean
        enriched += 1

    return mapping, EnrichmentReport(
        attempted=attempted,
        enriched=enriched,
        without_gtin=without_gtin,
        failed=failed,
    )
