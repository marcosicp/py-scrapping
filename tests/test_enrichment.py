"""The EAN enrichment loop: pure, offline behavior (ean-enrichment T3).

``enrich_eans`` receives the site knowledge as injected seams and never
touches HTTP, a database or Flask; the tests drive it with canned pages and
recording fakes.
"""

from __future__ import annotations

from api.services.enrichment import EnrichmentReport, enrich_eans


class RecordingReporter:
    """ProgressReporter fake collecting every message."""

    def __init__(self) -> None:
        self.messages: list[str] = []

    def __call__(self, text: str) -> None:
        self.messages.append(text)


def make_doc(sku, ean=None, name="x"):
    doc = {"supermercado": "La Anónima", "name": name, "sku": sku}
    if ean is not None:
        doc["ean"] = ean
    return doc


def test_happy_path_maps_every_sku_to_its_gtin():
    docs = [make_doc("3100001"), make_doc("3100002")]
    pages = {
        "https://www.laanonima.com.ar/x/art_3100001/":
            '{"@type": "Product", "gtin": "7790895000123"}',
        "https://www.laanonima.com.ar/x/art_3100002/":
            '{"@type": "Product", "gtin": "7790895000456"}',
    }
    reporter = RecordingReporter()
    fetches: list[str] = []

    mapping, report = enrich_eans(
        docs,
        url_for=lambda sku: f"https://www.laanonima.com.ar/x/art_{sku}/",
        extract_ean=lambda html: "7790895000123" if "000123" in html else
        "7790895000456",
        fetch=lambda url: (fetches.append(url), pages[url])[1],
        report=reporter)

    assert fetches == [
        "https://www.laanonima.com.ar/x/art_3100001/",
        "https://www.laanonima.com.ar/x/art_3100002/",
    ]
    assert mapping == {
        "3100001": "7790895000123",
        "3100002": "7790895000456",
    }
    assert report == EnrichmentReport(attempted=2, enriched=2,
                                      without_gtin=0, failed=0)


def test_documents_with_an_existing_ean_are_never_attempted():
    """N-3: only empty-ean documents are candidates — an existing ean is
    never re-fetched, never overwritten."""
    docs = [make_doc("3100001", ean="7790000000001"),
            make_doc("3100002")]
    fetches: list[str] = []

    mapping, report = enrich_eans(
        docs,
        url_for=lambda sku: f"https://x/{sku}",
        extract_ean=lambda html: "7790895000123",
        fetch=lambda url: (fetches.append(url), '{"gtin": "7790895000123"}')[1],
        report=RecordingReporter())

    assert fetches == ["https://x/3100002"]
    assert mapping == {"3100002": "7790895000123"}
    assert report == EnrichmentReport(attempted=1, enriched=1,
                                      without_gtin=0, failed=0)


def test_a_document_without_a_sku_is_skipped():
    docs = [make_doc(None), make_doc("3100001")]
    fetches: list[str] = []

    mapping, report = enrich_eans(
        docs,
        url_for=lambda sku: f"https://x/{sku}",
        extract_ean=lambda html: "7790895000123",
        fetch=lambda url: (fetches.append(url), '{"gtin": "1"}')[1],
        report=RecordingReporter())

    assert fetches == ["https://x/3100001"]
    assert mapping == {"3100001": "7790895000123"}
    assert report == EnrichmentReport(attempted=1, enriched=1,
                                      without_gtin=0, failed=0)


def test_a_page_without_a_gtin_counts_as_without_gtin():
    docs = [make_doc("3100001")]

    mapping, report = enrich_eans(
        docs,
        url_for=lambda sku: f"https://x/{sku}",
        extract_ean=lambda html: None,
        fetch=lambda url: "<html><p>sin gtin</p></html>",
        report=RecordingReporter())

    assert mapping == {}
    assert report == EnrichmentReport(attempted=1, enriched=0,
                                      without_gtin=1, failed=0)


def test_a_raising_fetch_counts_as_failed_and_the_walk_continues():
    docs = [make_doc("3100001"), make_doc("3100002")]
    fetches: list[str] = []

    def fetch(url):
        fetches.append(url)
        if "3100001" in url:
            raise ConnectionError("boom")
        return '{"@type": "Product", "gtin": "7790895000456"}'

    reporter = RecordingReporter()
    mapping, report = enrich_eans(
        docs,
        url_for=lambda sku: f"https://x/{sku}",
        extract_ean=lambda html: "7790895000456",
        fetch=fetch,
        report=reporter)

    assert fetches == ["https://x/3100001", "https://x/3100002"]
    assert mapping == {"3100002": "7790895000456"}
    assert report == EnrichmentReport(attempted=2, enriched=1,
                                      without_gtin=0, failed=1)
    assert any("3100001" in message for message in reporter.messages)


def test_a_non_string_body_counts_as_failed():
    """A seam that answers something that is not page text is a failure of
    the same kind: counted and reported, never fed to the extractor."""
    docs = [make_doc("3100001")]

    mapping, report = enrich_eans(
        docs,
        url_for=lambda sku: f"https://x/{sku}",
        extract_ean=lambda html: (_ for _ in ()).throw(
            AssertionError("extractor must not see a non-string body")),
        fetch=lambda url: None,
        report=RecordingReporter())

    assert mapping == {}
    assert report == EnrichmentReport(attempted=1, enriched=0,
                                      without_gtin=0, failed=1)


def test_a_duplicate_sku_produces_one_mapping_entry():
    """Two candidate documents with the same ``sku`` are the same product:
    one fetch, one mapping entry (N-3: never the same request twice)."""
    docs = [make_doc("3100001", name="Coca 2lt"),
            make_doc("3100001", name="Coca 2lt (dup)")]
    fetches: list[str] = []

    mapping, report = enrich_eans(
        docs,
        url_for=lambda sku: f"https://x/{sku}",
        extract_ean=lambda html: "7790895000123",
        fetch=lambda url: (fetches.append(url), '{"gtin": "1"}')[1],
        report=RecordingReporter())

    assert fetches == ["https://x/3100001"]
    assert mapping == {"3100001": "7790895000123"}
    assert report == EnrichmentReport(attempted=1, enriched=1,
                                      without_gtin=0, failed=0)


def test_sleep_runs_between_requests_but_never_after_the_last():
    docs = [make_doc("3100001"), make_doc("3100002"), make_doc("3100003")]
    timeline: list[str] = []

    def fetch(url):
        timeline.append(f"fetch:{url}")
        return '{"gtin": "1"}'

    def sleep(seconds):
        timeline.append(f"sleep:{seconds}")

    enrich_eans(
        docs,
        url_for=lambda sku: f"https://x/{sku}",
        extract_ean=lambda html: "7790895000123",
        fetch=fetch,
        report=RecordingReporter(),
        sleep=sleep)

    # -- fetch, pause, fetch, pause, fetch — and nothing after the last one
    assert timeline == [
        "fetch:https://x/3100001",
        "sleep:0.4",
        "fetch:https://x/3100002",
        "sleep:0.4",
        "fetch:https://x/3100003",
    ]


def test_sleep_is_not_called_with_a_single_candidate():
    timeline: list[str] = []

    enrich_eans(
        [make_doc("3100001")],
        url_for=lambda sku: f"https://x/{sku}",
        extract_ean=lambda html: "7790895000123",
        fetch=lambda url: '{"gtin": "1"}',
        report=RecordingReporter(),
        sleep=lambda seconds: timeline.append("sleep"))

    assert timeline == []


def test_without_sleep_injection_the_walk_never_pauses():
    """The parameter is optional: no ``sleep`` means no pause at all."""
    mapping, report = enrich_eans(
        [make_doc("3100001")],
        url_for=lambda sku: f"https://x/{sku}",
        extract_ean=lambda html: "7790895000123",
        fetch=lambda url: '{"gtin": "1"}',
        report=RecordingReporter())

    assert report == EnrichmentReport(attempted=1, enriched=1,
                                      without_gtin=0, failed=0)
