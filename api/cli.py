"""Command-line scraper runner: ``python -m api.cli`` (T12).

Runs one supermarket scraper straight from the shell, without Flask,
gunicorn or SocketIO: the same ``ScraperManager`` the app uses, with a
plain ``ConsoleReporter`` printing progress to stdout.

Subcommands:

- ``list``: one line per registered scraper, in registration order.
- ``run <slug> [--category <name>]``: run one scraper and wait for it.
- ``enrich-ean [--chain <slug>] [--limit N] [--sleep SECONDS]
  [--max-failures N]`` (ean-enrichment T4, N-6): fill the missing ``ean``
  of one chain from its product detail pages —
  source of truth ``odd/tasks/ean-enrichment.md``. La Anónima publishes the
  barcode (``gtin``) only on the detail page, and any slug answers there, so
  the walk is ``detail_url(sku)`` + ``gtin_of(html)`` per candidate at a
  configurable pace (N-5). It is its own command, never a step of the scrape
  (N-1): idempotent by construction — only empty-ean documents are fetched,
  an existing ``ean`` is never overwritten, and the write goes through
  ``update_eans``, a targeted update that touches nothing else (N-4).
  ``--chain`` defaults to ``laanonima``; an unknown chain is a loud error
  (exit 3), because only the chains in ``EAN_SOURCES`` have a known barcode
  source (SuperMami publishes none anywhere reachable — measured). The walk
  is paced by default: ``--sleep`` is 1.5 s because a backfill at 0.4 s got
  La Anónima to 403-block the whole domain from this machine (the incident
  in ``odd/tasks/ean-enrichment.md``), and ``--max-failures`` (default 5)
  stops the walk — printing ``abortado tras N fallos consecutivos`` and
  exiting 4 — once that many requests in a row fail, so a shell loop never
  starts the next chunk against a site that is refusing. Aborting is the
  correct behaviour: the site is telling you to stop, and resuming later is
  free because the command skips documents that already carry an ``ean``.
- ``coverage``: read-only catalog coverage report (category-coverage T4;
  comparator focus T3): a per-category block — documents, grouped rows, rows
  carried by 2+ chains and the resulting percentage, with NO majority
  binning: a row counts under every category its members carry — then a
  per-chain block over the five chain buckets, and a total line over the
  whole catalog. Grouping goes through the same ``group_products`` the API
  uses, so the number cannot drift from what the dashboard shows. Unlike
  ``run``, it reads ``.env``
  exactly like ``app.py`` and prints the resolved source, because the local
  default (``localhost``/``lalistitadev``) holds no ``ean`` and no
  ChangoMás and would understate the coverage it exists to measure.

Environment file: every subcommand honours ``LALISTITA_ENV_FILE``, which
names the env file to load (see ``api.config.load_env_file``). Each
subcommand carries its own default, on purpose:

- ``run``: no default — the shell environment decides, so a scraper is
  never silently retargeted at whatever ``.env`` (the production database)
  says; only an explicit selector points it somewhere else.
- ``enrich-ean``: no default, the same rule as ``run`` — an enrichment walk
  fires thousands of targeted writes, so it must never run against whatever
  ``.env`` says.
- ``coverage``: ``.env``, the same default ``app.py`` uses, so the report
  keeps measuring the database the dashboard reads.
- ``list``: no env file at all — it reads no database.

An exported variable always wins over the loaded file. An explicitly
selected file that does not exist fails the command instead of quietly
falling back to the shell defaults: a typo in ``LALISTITA_ENV_FILE`` must
not run a scraper against the wrong database. A missing *default* ``.env``
is not an error — a fresh clone and CI have none.

Exit codes: 0 succeeded, 1 failed, 2 stopped, 3 scraper-control error
(unknown slug, invalid category or already running, unknown ``enrich-ean``
chain), 4 the ``enrich-ean`` walk aborted on consecutive failures (N-6).
``coverage`` exits 0.

The module stays thin: no scraping logic, no Flask import, no
``current_app``. ``build_client``, ``ScraperManager`` and
``default_registry`` are read from module attributes, which is the seam
the tests monkeypatch to stay offline.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable

from pymongo import MongoClient

from api.config import Settings, load_env_file
from api.mongo import build_client
from api.repositories import RepositoryUnavailable
from api.repositories.products import MongoProductRepository
from api.scrapers.errors import ScraperError
from api.scrapers.http import build_http_session
from api.scrapers.laanonima import detail_url, gtin_of
from api.scrapers.registry import ScraperRegistry, default_registry
from api.services.enrichment import enrich_eans
from api.services.matching import group_products
from api.services.scraping import RunState, RunStatus, \
    ScraperManager

# Terminal state -> exit code. Anything unexpected (there is no such
# terminal state today) is treated as a failure.
_EXIT_CODES: dict[RunState, int] = {
    RunState.SUCCEEDED: 0,
    RunState.FAILED: 1,
    RunState.STOPPED: 2,
}


class ConsoleReporter:
    """ProgressReporter (``api.services.scraping``) printing to stdout."""

    def message(self, slug: str, text: str) -> None:
        print(f"[{slug}] {text}")

    def state(self, status: RunStatus) -> None:
        print(f"[{status.slug}] state: {status.state.value}")


def build_manager(settings: Settings) -> ScraperManager:
    """The real wiring: Mongo-backed repository over the default registry.

    ``connect=False`` defers the server handshake to the first operation,
    so building the client never blocks startup. The TLS trust store comes
    from `api/mongo.py::build_client`, the same rule Flask uses (D-19).
    """
    registry: ScraperRegistry = default_registry()
    client = build_client(settings)
    repository = MongoProductRepository(client[settings.mongodb_db])
    return ScraperManager(registry, repository, reporter=ConsoleReporter())


def cmd_list(args: argparse.Namespace) -> int:
    for cls in default_registry().classes():
        categories = ", ".join(cls.categories) or "-"
        print(f"{cls.slug}: {cls.label} ({categories})")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    # No default on purpose: `run` keeps the shell's environment unless the
    # operator selects a file with LALISTITA_ENV_FILE — it must never be
    # silently retargeted at what `.env` (the production database) says.
    load_env_file()
    settings = Settings.from_env()
    manager = build_manager(settings)
    slug: str = args.slug
    try:
        manager.start(slug, args.category)
        try:
            status = manager.wait(slug)
        except KeyboardInterrupt:
            # The user pressed Ctrl+C: request a cooperative stop and keep
            # waiting until the worker thread lands in its terminal state.
            try:
                manager.stop(slug)
            except ScraperError:
                pass  # The run already finished on its own.
            status = manager.wait(slug)
    except ScraperError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3

    message = status.message if status.message is not None else "-"
    print(f"[{status.slug}] {status.state.value} "
          f"saved: {status.saved} message: {message}")
    return _EXIT_CODES.get(status.state, 1)


# -- EAN sources (ean-enrichment N-2): chains whose site publishes a
# barcode somewhere reachable, with the two site-knowledge functions each
# one contributes. Adding a chain means adding two functions here, not
# editing the engine. SuperMami publishes no barcode anywhere reachable
# (measured, ``odd/tasks/ean-enrichment.md``) and is deliberately absent.
EAN_SOURCES: dict[str, tuple[Callable[[str], str],
                             Callable[[str], str | None]]] = {
    "laanonima": (detail_url, gtin_of),
}


def cmd_enrich_ean(args: argparse.Namespace) -> int:
    """Fill the missing ``ean`` of one chain (ean-enrichment T4).

    Reads the catalog through ``MongoProductRepository``, keeps the
    documents of ``--chain`` (validated against ``EAN_SOURCES`` — an
    unknown chain is a clear error, never a silent no-op), bounds the
    candidates with ``--limit`` (0 or absent means all) and walks them
    through ``enrich_eans`` with La Anónima's ``detail_url``/``gtin_of`` and
    the shared ctx-less HTTP session. ``--sleep`` (default 1.5) is the pace
    between detail-page requests: the operator's value overrides the
    suggested pause the loop injects. ``--max-failures`` (default 5, N-6) is
    forwarded as ``max_consecutive_failures``: after that many consecutive
    failures the walk stops, and a paced backfill of thousands of pages must
    stop when the site starts refusing instead of hammering the door.

    The mapping the service produced is written through
    ``update_eans`` — never ``replace_products``, which owns whole slices
    (N-4) — and one summary line per counter is printed, plus how many
    documents the repository actually modified. Exits 0 for a clean walk, 4
    when the walk aborted on consecutive failures so a shell loop stops
    instead of starting the next chunk.
    """
    source = EAN_SOURCES.get(args.chain)
    if source is None:
        known = ", ".join(sorted(EAN_SOURCES))
        print(f"error: no EAN source for chain '{args.chain}' "
              f"(known: {known})", file=sys.stderr)
        return 3
    url_for, extract_ean = source
    # The stored documents carry the scraper's ``label`` as their
    # ``supermercado`` (the scrapers save ``self.label``), so both the read
    # filter and the write are keyed on the label, not on the slug.
    label = default_registry().get(args.chain).label

    # No default on purpose: same rule as `run`, never retarget a database
    # by accident — only an explicit LALISTITA_ENV_FILE points this somewhere.
    load_env_file()
    settings = Settings.from_env()
    try:
        client = build_client(settings)
        repository = MongoProductRepository(client[settings.mongodb_db])
        documents = repository.find_all()
        # Only the documents that still need it are candidates, before the
        # limit is applied: a bounded run must attempt `limit` products, not
        # hand the service a slice of already-enriched ones. This is also what
        # makes a chunked backfill possible (`--limit 800` repeatedly walks
        # forward instead of re-reading the same first records).
        candidates = [doc for doc in documents
                      if doc.get("supermercado") == label
                      and not doc.get("ean") and doc.get("sku")]
        if args.limit > 0:
            candidates = candidates[:args.limit]

        session = build_http_session()

        def fetch(url: str) -> str:
            response = session.get(url, timeout=30)
            if response.status_code != 200:
                raise RuntimeError(f"HTTP {response.status_code}")
            return response.text

        mapping, enrich_report = enrich_eans(
            candidates,
            url_for=url_for,
            extract_ean=extract_ean,
            fetch=fetch,
            report=lambda text: print(f"[enrich-ean] {text}"),
            sleep=lambda suggested: time.sleep(args.sleep),
            max_consecutive_failures=args.max_failures)
        modified = repository.update_eans(label, mapping)
    except RepositoryUnavailable as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"attempted: {enrich_report.attempted}")
    print(f"enriched: {enrich_report.enriched}")
    print(f"without_gtin: {enrich_report.without_gtin}")
    print(f"failed: {enrich_report.failed}")
    print(f"modified: {modified}")
    if enrich_report.aborted:
        print(f"[enrich-ean] abortado tras {args.max_failures} "
              "fallos consecutivos")
        return 4
    return 0


def _source_of(settings: Settings) -> str:
    """``<database> @ <host>`` with every credential stripped.

    The coverage report is the only place that needs it: ``lalistitadev``
    names both the local ``mongod`` and the deployed cluster, so the database
    name alone cannot tell the reader which one produced the numbers.
    """
    host = settings.mongodb_uri.rsplit("@", 1)[-1].split("/", 1)[0]
    return f"{settings.mongodb_db} @ {host}"


def cmd_coverage(args: argparse.Namespace) -> int:
    """Read-only coverage report (category-coverage T4, C-7; comparator
    focus T3, F-3..F-5).

    Reads the catalog through the same repository the API uses and groups it
    with ``matching.group_products`` (never a private reimplementation), with
    ``include_member_categories=True`` so every row carries the slugs its
    member documents carry. Two blocks follow the ``source:`` line:

    * **por categoria** — NO majority binning: a row counts under EVERY slug
      in its ``categorias``, so a cross-category comparison appears in both
      instead of being lost to a vote (F-3). A row with no member category
      counts under ``(sin categoria)``. Documents are keyed on each
      document's own ``categoria``, as always. Categories sort
      alphabetically with ``(sin categoria)`` last, then a ``total`` line.
    * **por cadena** — per chain bucket (F-4), in the payload's fixed order:
      documents of that chain, rows carrying it, how many are comparable
      (2+ chains) and the percentage.

    Both blocks print documents, rows and comparable rows (F-5): volume is
    reported, never celebrated. The report stays read-only.

    ``load_env_file('.env')`` is called here and not for ``run`` on purpose:
    this report must measure the database the dashboard reads, and pointing
    it at the local default silently reports a six-points-worse figure (the
    local copy carries no ``ean``, so the whole EAN layer is absent). ``run``
    keeps its current environment contract instead of retargeting a scraper
    at whatever ``.env`` says. ``LALISTITA_ENV_FILE`` retargets both without
    changing these defaults. Existing environment variables still win:
    ``load_env_file`` never overrides them.
    """
    load_env_file(".env")
    settings = Settings.from_env()
    client = build_client(settings)
    repository = MongoProductRepository(client[settings.mongodb_db])
    docs = repository.find_all()
    payload = group_products(docs, include_member_categories=True)
    rows = payload["productos"]

    doc_counts: dict[str | None, int] = {}
    for doc in docs:
        categoria = doc.get("categoria")
        key = categoria if isinstance(categoria, str) and categoria.strip() \
            else None
        doc_counts[key] = doc_counts.get(key, 0) + 1

    # -- F-3: a row counts under EVERY slug its members carry; a row whose
    # members carry none counts under None ((sin categoria)).
    row_counts: dict[str | None, int] = {}
    multi_counts: dict[str | None, int] = {}
    for row in rows:
        is_multi = len(row["offers"]) >= 2
        keys = row.get("categorias") or [None]
        for key in keys:
            row_counts[key] = row_counts.get(key, 0) + 1
            if is_multi:
                multi_counts[key] = multi_counts.get(key, 0) + 1

    def line(label: str, n_docs: int, n_rows: int, n_multi: int) -> None:
        pct = f"{100.0 * n_multi / n_rows:.1f}%" if n_rows else "0.0%"
        print(f"{label:<16}{n_docs:>8}{n_rows:>7}{n_multi:>7}{pct:>10}")

    print(f"source: {_source_of(settings)}")

    print("por categoria (una fila cuenta en cada categoria que porta):")
    print(f"{'categoria':<16}{'docs':>8}{'rows':>7}{'2+chains':>7}{'pct':>10}")
    categories = sorted(set(doc_counts) | set(row_counts),
                        key=lambda key: (key is None, key))
    for key in categories:
        line("(sin categoria)" if key is None else key,
             doc_counts.get(key, 0), row_counts.get(key, 0),
             multi_counts.get(key, 0))
    # -- the total counts every row once, never once per category it carries
    line("total", len(docs), len(rows),
         sum(1 for row in rows if len(row["offers"]) >= 2))

    # -- F-4: per chain, in the payload's fixed bucket order. The payload
    # carries the buckets as top-level keys ("productos" is the only other
    # key), so the order comes from matching itself, not from a copy here.
    chain_keys = [key for key in payload if key != "productos"]
    chain_rows: dict[str, int] = {}
    chain_multi: dict[str, int] = {}
    for row in rows:
        is_multi = len(row["offers"]) >= 2
        for chain in row["offers"]:
            chain_rows[chain] = chain_rows.get(chain, 0) + 1
            if is_multi:
                chain_multi[chain] = chain_multi.get(chain, 0) + 1

    print("por cadena:")
    print(f"{'cadena':<16}{'docs':>8}{'rows':>7}{'2+chains':>7}{'pct':>10}")
    for chain in chain_keys:
        line(chain, payload[chain], chain_rows.get(chain, 0),
             chain_multi.get(chain, 0))

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="api.cli",
        description="List and run the supermarket scrapers without Flask.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="list the registered scrapers")

    run_parser = subparsers.add_parser("run", help="run one scraper")
    run_parser.add_argument("slug", help="registered scraper slug")
    run_parser.add_argument("--category", default=None,
                            help="optional category for scrapers that "
                                 "accept one")

    subparsers.add_parser(
        "coverage",
        help="read-only per-category coverage report over the catalog")

    ean_parser = subparsers.add_parser(
        "enrich-ean",
        help="fill the missing barcodes (ean) of one chain from its "
             "product detail pages")
    ean_parser.add_argument(
        "--chain", default="laanonima",
        help="chain to enrich; must have a known EAN source "
             "(default: laanonima)")
    ean_parser.add_argument(
        "--limit", type=int, default=0,
        help="bound the candidates; 0 or absent means all")
    ean_parser.add_argument(
        "--sleep", type=float, default=1.5,
        help="seconds between detail-page requests (default: 1.5) — a "
             "backfill of thousands of pages must be paced; 0.4 s got "
             "La Anónima to 403-block the whole domain, see the incident "
             "in odd/tasks/ean-enrichment.md")
    ean_parser.add_argument(
        "--max-failures", type=int, default=5,
        help="stop the walk after this many consecutive failed requests "
             "(default: 5; 0 or less never aborts); an aborted walk "
             "exits 4")

    args = parser.parse_args(argv)
    if args.command == "list":
        return cmd_list(args)
    if args.command == "coverage":
        return cmd_coverage(args)
    if args.command == "enrich-ean":
        return cmd_enrich_ean(args)
    return cmd_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
