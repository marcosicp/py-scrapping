"""Command-line scraper runner: ``python -m api.cli`` (T12).

Runs one supermarket scraper straight from the shell, without Flask,
gunicorn or SocketIO: the same ``ScraperManager`` the app uses, with a
plain ``ConsoleReporter`` printing progress to stdout.

Subcommands:

- ``list``: one line per registered scraper, in registration order.
- ``run <slug> [--category <name>]``: run one scraper and wait for it.

Exit codes: 0 succeeded, 1 failed, 2 stopped, 3 scraper-control error
(unknown slug, invalid category or already running).

The module stays thin: no scraping logic, no Flask import, no
``current_app``. ``build_client``, ``ScraperManager`` and
``default_registry`` are read from module attributes, which is the seam
the tests monkeypatch to stay offline.
"""

from __future__ import annotations

import argparse
import sys

from pymongo import MongoClient

from api.config import Settings
from api.mongo import build_client
from api.repositories.products import MongoProductRepository
from api.scrapers.errors import ScraperError
from api.scrapers.registry import ScraperRegistry, default_registry
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

    args = parser.parse_args(argv)
    if args.command == "list":
        return cmd_list(args)
    return cmd_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
