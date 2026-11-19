"""Command-line scraper runner: ``python -m api.cli`` (T12).

Runs one supermarket scraper straight from the shell, without Flask,
gunicorn or SocketIO: the same ``ScraperManager`` the app uses, with a
plain ``ConsoleReporter`` printing progress to stdout.

Subcommands:

- ``list``: one line per registered scraper, in registration order.
- ``run <slug> [--category <name>]``: run one scraper and wait for it.
- ``coverage``: per-category read-only catalog report (category-coverage
  T4): documents, grouped rows, rows carried by 2+ chains and the resulting
  percentage, plus a total line over the whole catalog. Grouping goes
  through the same ``group_products`` the API uses, so the number cannot
  drift from what the dashboard shows. Unlike ``run``, it reads ``.env``
  exactly like ``app.py`` and prints the resolved source, because the local
  default (``localhost``/``lalistitadev``) holds no ``ean`` and no
  ChangoMás and would understate the coverage it exists to measure.

Environment file: both entry points honour ``LALISTITA_ENV_FILE``, which
names the env file to load (see ``api.config.load_env_file``). Each
subcommand carries its own default, on purpose:

- ``run``: no default — the shell environment decides, so a scraper is
  never silently retargeted at whatever ``.env`` (the production database)
  says; only an explicit selector points it somewhere else.
- ``coverage``: ``.env``, the same default ``app.py`` uses, so the report
  keeps measuring the database the dashboard reads.
- ``list``: no env file at all — it reads no database.

An exported variable always wins over the loaded file. An explicitly
selected file that does not exist fails the command instead of quietly
falling back to the shell defaults: a typo in ``LALISTITA_ENV_FILE`` must
not run a scraper against the wrong database. A missing *default* ``.env``
is not an error — a fresh clone and CI have none.

Exit codes: 0 succeeded, 1 failed, 2 stopped, 3 scraper-control error
(unknown slug, invalid category or already running). ``coverage`` exits 0.

The module stays thin: no scraping logic, no Flask import, no
``current_app``. ``build_client``, ``ScraperManager`` and
``default_registry`` are read from module attributes, which is the seam
the tests monkeypatch to stay offline.
"""

from __future__ import annotations

import argparse
import sys

from pymongo import MongoClient

from api.config import Settings, load_env_file
from api.mongo import build_client
from api.repositories.products import MongoProductRepository
from api.scrapers.errors import ScraperError
from api.scrapers.registry import ScraperRegistry, default_registry
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


def _source_of(settings: Settings) -> str:
    """``<database> @ <host>`` with every credential stripped.

    The coverage report is the only place that needs it: ``lalistitadev``
    names both the local ``mongod`` and the deployed cluster, so the database
    name alone cannot tell the reader which one produced the numbers.
    """
    host = settings.mongodb_uri.rsplit("@", 1)[-1].split("/", 1)[0]
    return f"{settings.mongodb_db} @ {host}"


def cmd_coverage(args: argparse.Namespace) -> int:
    """Read-only per-category coverage report (category-coverage T4, C-7).

    Reads the catalog through the same repository the API uses, groups it
    with ``matching.group_products`` (never a private reimplementation) and
    prints, per category: documents, rows, rows carried by 2+ chains and the
    resulting percentage; then a total line over the whole catalog. Rows
    whose ``categoria`` is None report under ``(sin categoria)``, last.

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
    rows = group_products(docs)["productos"]

    doc_counts: dict[str | None, int] = {}
    for doc in docs:
        categoria = doc.get("categoria")
        key = categoria if isinstance(categoria, str) and categoria.strip() \
            else None
        doc_counts[key] = doc_counts.get(key, 0) + 1

    row_counts: dict[str | None, int] = {}
    multi_counts: dict[str | None, int] = {}
    for row in rows:
        key = row["categoria"]
        row_counts[key] = row_counts.get(key, 0) + 1
        if len(row["offers"]) >= 2:
            multi_counts[key] = multi_counts.get(key, 0) + 1

    def line(label: str, n_docs: int, n_rows: int, n_multi: int) -> None:
        pct = f"{100.0 * n_multi / n_rows:.1f}%" if n_rows else "0.0%"
        print(f"{label:<16}{n_docs:>8}{n_rows:>7}{n_multi:>7}{pct:>10}")

    print(f"source: {_source_of(settings)}")
    print(f"{'categoria':<16}{'docs':>8}{'rows':>7}{'2+chains':>7}{'pct':>10}")
    categories = sorted(set(doc_counts) | set(row_counts),
                        key=lambda key: (key is None, key))
    for key in categories:
        line("(sin categoria)" if key is None else key,
             doc_counts.get(key, 0), row_counts.get(key, 0),
             multi_counts.get(key, 0))
    line("total", len(docs), len(rows), sum(multi_counts.values()))

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

    args = parser.parse_args(argv)
    if args.command == "list":
        return cmd_list(args)
    if args.command == "coverage":
        return cmd_coverage(args)
    return cmd_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
