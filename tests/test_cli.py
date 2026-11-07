"""CLI scraper runner: ``python -m api.cli`` (T12).

Offline by construction: the Mongo client and the manager are small fakes
monkeypatched over the module attributes, so no network, database, browser
or scraper ever runs.
"""

import api.cli as cli
import pytest

from api.scrapers.errors import AlreadyRunning, UnknownScraper
from api.scrapers.registry import ScraperRegistry, default_registry
from api.services.scraping import RunState, RunStatus
from tests.fakes import make_scraper


class FakeDatabase:
    # MongoProductRepository only subscribes to a collection at init time;
    # a stand-in that answers any subscript is enough.
    def __getitem__(self, name):
        return f"<fake collection {name}>"


class FakeMongoClient:
    """Records how it was built; never connects anywhere."""

    instances: list["FakeMongoClient"] = []

    def __init__(self, uri, connect=False):
        self.uri = uri
        self.connect = connect
        self.databases: dict[str, FakeDatabase] = {}
        FakeMongoClient.instances.append(self)

    def __getitem__(self, name):
        if name not in self.databases:
            self.databases[name] = FakeDatabase()
        return self.databases[name]


class FakeManager:
    """Never starts anything: records calls and replays one final status."""

    def __init__(self, registry=None, repository=None, reporter=None):
        self.registry = registry
        self.repository = repository
        self.reporter = reporter
        self.started: list[tuple[str, str | None]] = []
        self.stopped: list[str] = []
        self.wait_calls = 0
        self.start_error: Exception | None = None
        self.interrupt_first_wait = False
        self.status = RunStatus(slug="disco", label="Disco")

    def start(self, slug, category=None):
        self.started.append((slug, category))
        if self.start_error is not None:
            raise self.start_error

    def stop(self, slug):
        self.stopped.append(slug)

    def wait(self, slug):
        self.wait_calls += 1
        if self.interrupt_first_wait and self.wait_calls == 1:
            raise KeyboardInterrupt
        return self.status


def status_for(state: RunState, *, saved: int = 0, message: str | None = None,
               slug: str = "disco") -> RunStatus:
    return RunStatus(slug=slug, label=slug.title(), state=state, saved=saved,
                     message=message)


@pytest.fixture
def fake_env(monkeypatch):
    """Swap the CLI's Mongo client, registry and manager for fakes."""
    FakeMongoClient.instances = []
    # -- the CLI builds its client through api.mongo.build_client (D-19), so the
    # seam to replace is the factory, not pymongo's MongoClient
    monkeypatch.setattr(
        cli, "build_client",
        lambda settings: FakeMongoClient(settings.mongodb_uri, connect=False),
    )
    registry = ScraperRegistry([
        make_scraper("disco", "Disco", lambda ctx: None),
        make_scraper("carrefour", "Carrefour", lambda ctx: None),
    ])
    monkeypatch.setattr(cli, "default_registry", lambda: registry)
    manager = FakeManager()
    monkeypatch.setattr(cli, "ScraperManager", lambda *args, **kwargs: manager)
    return manager


# -- list -----------------------------------------------------------------------

def test_list_prints_every_registered_slug_and_exits_0(capsys):
    exit_code = cli.main(["list"])
    out = capsys.readouterr().out
    assert exit_code == 0
    for slug in default_registry().slugs():
        assert slug in out


# -- run: exit code per final state ------------------------------------------------

def test_run_succeeded_returns_0_and_prints_summary(fake_env, capsys):
    fake_env.status = status_for(RunState.SUCCEEDED, saved=7, message="Listo")
    assert cli.main(["run", "disco"]) == 0
    out = capsys.readouterr().out
    assert "succeeded" in out
    assert "7" in out
    assert "Listo" in out


def test_run_failed_returns_1(fake_env, capsys):
    fake_env.status = status_for(RunState.FAILED, message="boom")
    assert cli.main(["run", "disco"]) == 1
    out = capsys.readouterr().out
    assert "failed" in out
    assert "boom" in out


def test_run_stopped_returns_2(fake_env):
    fake_env.status = status_for(RunState.STOPPED)
    assert cli.main(["run", "disco"]) == 2


# -- run: error paths ---------------------------------------------------------

def test_run_unknown_slug_returns_3_without_traceback(fake_env, capsys):
    fake_env.start_error = UnknownScraper("ghost")
    exit_code = cli.main(["run", "ghost"])
    captured = capsys.readouterr()
    assert exit_code == 3
    assert "Unknown scraper 'ghost'" in captured.out + captured.err
    assert "Traceback" not in captured.out + captured.err


def test_run_already_running_returns_3(fake_env):
    fake_env.start_error = AlreadyRunning("disco")
    assert cli.main(["run", "disco"]) == 3


# -- run: wiring ----------------------------------------------------------------

def test_run_passes_category_through(fake_env):
    fake_env.status = status_for(RunState.SUCCEEDED)
    assert cli.main(["run", "disco", "--category", "almacen"]) == 0
    assert fake_env.started == [("disco", "almacen")]


def test_run_builds_mongo_client_without_connecting(fake_env):
    fake_env.status = status_for(RunState.SUCCEEDED)
    cli.main(["run", "disco"])
    assert len(FakeMongoClient.instances) == 1
    client = FakeMongoClient.instances[0]
    assert client.connect is False


def test_keyboard_interrupt_calls_stop_and_returns_2(fake_env):
    fake_env.interrupt_first_wait = True
    fake_env.status = status_for(RunState.STOPPED)
    assert cli.main(["run", "disco"]) == 2
    assert fake_env.stopped == ["disco"]
    assert fake_env.wait_calls == 2
