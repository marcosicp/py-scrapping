"""CLI scraper runner: ``python -m api.cli`` (T12).

Offline by construction: the Mongo client and the manager are small fakes
monkeypatched over the module attributes, so no network, database, browser
or scraper ever runs.
"""

import re
import time
from types import SimpleNamespace

import api.cli as cli
import pytest

from api.config import Settings
from api.repositories import RepositoryUnavailable
from api.scrapers.errors import AlreadyRunning, UnknownScraper
from api.scrapers.registry import ScraperRegistry, default_registry
from api.services.scraping import RunState, RunStatus
from tests.fakes import FakeCollection, InMemoryProductRepository, make_scraper


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


# -- coverage -------------------------------------------------------------------

class _CoverageDatabase:
    """Database stand-in that answers every subscript with one collection."""

    def __init__(self, collection):
        self._collection = collection

    def __getitem__(self, name):
        return self._collection


class _CoverageClient:
    """Client stand-in built by the monkeypatched ``build_client``."""

    def __init__(self, collection):
        self._database = _CoverageDatabase(collection)

    def __getitem__(self, name):
        return self._database


@pytest.fixture
def coverage_collection(monkeypatch):
    """A FakeCollection the CLI reads through the real MongoProductRepository,
    with ``build_client`` swapped for a fake that never connects.

    ``load_env_file`` is neutralised here so no coverage test can read the
    repository's real ``.env``: ``cmd_coverage`` loads it on purpose, and
    letting it write into ``os.environ`` would leak a deployed URI into every
    later test that calls ``Settings.from_env()``.
    """
    collection = FakeCollection()
    monkeypatch.setattr(
        cli, "build_client",
        lambda settings: _CoverageClient(collection))
    monkeypatch.setattr(cli, "load_env_file", lambda *args, **kwargs: None)
    return collection


def _line(out, label):
    for line in out.splitlines():
        if line.split() and line.split()[0] == label:
            return line
    raise AssertionError(f"no line starting with {label!r} in:\n{out}")


_COVERAGE_DOCS = [
    # almacen: one EAN pair across chains -> 1 row with 2 chains
    {"supermercado": "disco", "name": "Aceite Natura", "price": 1200,
     "ean": "7790272001005", "categoria": "almacen"},
    {"supermercado": "carrefour", "name": "Aceite Natura", "price": 1150,
     "ean": "7790272001005", "categoria": "almacen"},
    {"supermercado": "disco", "name": "Fideos Lata", "price": 100,
     "categoria": "almacen"},
    # bebidas: one single-chain row
    {"supermercado": "supermami", "name": "Coca", "price": 800,
     "categoria": "bebidas"},
    # no categoria at all
    {"supermercado": "disco", "name": "Pan Lactal", "price": 300},
]


def test_coverage_prints_sorted_categories_sin_categoria_last_and_total(
        coverage_collection, capsys):
    coverage_collection.documents = [dict(doc) for doc in _COVERAGE_DOCS]

    exit_code = cli.main(["coverage"])
    captured = capsys.readouterr()

    assert exit_code == 0
    out = captured.out
    # deterministic order: categories sorted, (sin categoria) last
    assert out.index("almacen") < out.index("bebidas") \
        < out.index("(sin categoria)")
    # almacen: 3 docs, 2 rows, 1 row with 2+ chains -> 50.0%
    assert re.search(r"^almacen\s+3\s+2\s+1\s+50\.0%$",
                     _line(out, "almacen"))
    # bebidas: 1 doc, 1 row, 0 multi-chain rows
    assert re.search(r"^bebidas\s+1\s+1\s+0\s+0\.0%$",
                     _line(out, "bebidas"))
    # total over the whole catalog: 5 docs, 4 rows, 1 multi -> 25.0%
    assert re.search(r"^total\s+5\s+4\s+1\s+25\.0%$", _line(out, "total"))


def test_coverage_groups_with_the_same_service_the_api_uses(
        coverage_collection, capsys):
    """The row figures must come from matching.group_products, not from a
    private reimplementation: an EAN pair across chains is ONE row."""
    coverage_collection.documents = [dict(doc) for doc in _COVERAGE_DOCS]
    cli.main(["coverage"])
    out = capsys.readouterr().out
    # the two Aceite docs are 2 of almacen's 3 docs but one single row
    assert re.search(r"^almacen\s+3\s+2\s+", _line(out, "almacen"))


def test_coverage_counts_a_cross_category_row_in_both_categories(
        coverage_collection, capsys):
    """F-3: no majority binning. One member carries ``almacen`` and the
    other ``limpieza``, so the EAN row counts in BOTH categories — the old
    majority vote buried the comparison under a single slug and the other
    looked empty."""
    coverage_collection.documents = [
        {"supermercado": "carrefour", "name": "Aceite Natura", "price": 100,
         "ean": "7790272001005", "categoria": "almacen"},
        {"supermercado": "disco", "name": "Aceite otra", "price": 90,
         "ean": "7790272001005", "categoria": "limpieza"},
    ]
    exit_code = cli.main(["coverage"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert re.search(r"^almacen\s+1\s+1\s+1\s+100\.0%$",
                     _line(out, "almacen"))
    assert re.search(r"^limpieza\s+1\s+1\s+1\s+100\.0%$",
                     _line(out, "limpieza"))
    # -- total stays whole-catalog: 2 docs, 1 row (carried by both
    # categories), 1 multi -> pct is multi/rows, so 100.0%
    assert re.search(r"^total\s+2\s+1\s+1\s+100\.0%$",
                     _line(out, "total"))


def test_coverage_is_read_only(coverage_collection, capsys):
    coverage_collection.documents = [dict(doc) for doc in _COVERAGE_DOCS]
    cli.main(["coverage"])
    # only the catalog read; never insert_many/delete_many
    assert coverage_collection.events == ["find"]


def test_coverage_loads_env_file_with_the_dotenv_default(
        coverage_collection, monkeypatch, capsys):
    """C-7 follow-up: the report must measure the database the dashboard
    reads, so it keeps today's ``.env`` default (the one ``app.py`` uses),
    which the ``LALISTITA_ENV_FILE`` selector can retarget without changing
    the call. The credential part of the URI never reaches stdout."""
    calls = []
    monkeypatch.setattr(
        cli, "load_env_file",
        lambda *args, **kwargs: calls.append(args) or None)
    monkeypatch.setattr(
        cli.Settings, "from_env", classmethod(lambda cls: Settings(
            secret_key="s",
            mongodb_uri="mongodb+srv://user:secret@cluster0.example.net/?x=1",
            mongodb_db="lalistitadev")))

    assert cli.main(["coverage"]) == 0
    out = capsys.readouterr().out

    assert calls == [(".env",)], \
        "cmd_coverage must default to .env exactly like app.py does"
    assert "source: lalistitadev @ cluster0.example.net" in out
    assert "secret" not in out
    assert "user:" not in out


def test_coverage_on_an_empty_database_prints_only_the_total(
        coverage_collection, capsys):
    exit_code = cli.main(["coverage"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert re.search(r"^total\s+0\s+0\s+0\s+0\.0%$", _line(out, "total"))


def test_coverage_counts_a_row_without_member_categories_under_sin_categoria(
        coverage_collection, capsys):
    """A row whose members carry no ``categoria`` at all reports under
    ``(sin categoria)`` — with no members there is no slug to bin under."""
    coverage_collection.documents = [
        {"supermercado": "disco", "name": "Pan Lactal", "price": 300},
    ]
    exit_code = cli.main(["coverage"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert re.search(r"^\(sin categoria\)\s+1\s+1\s+0\s+0\.0%$",
                     _line(out, "(sin"))


def test_coverage_prints_the_per_chain_block_in_payload_order(
        coverage_collection, capsys):
    """F-4: the comparator's weakest link is a chain. The block prints the
    payload's fixed bucket order (carre, disco, mami, hiper, chang) with,
    per bucket: documents, rows carrying that chain, comparable rows and
    the resulting share."""
    coverage_collection.documents = [dict(doc) for doc in _COVERAGE_DOCS]

    exit_code = cli.main(["coverage"])
    out = capsys.readouterr().out

    assert exit_code == 0
    # deterministic order: the payload's fixed bucket order
    assert out.index("carre") < out.index("disco") \
        < out.index("mami") < out.index("hiper") < out.index("chang")
    # carre: 1 doc, its aceite row (2+ chains) -> 100.0%
    assert re.search(r"^carre\s+1\s+1\s+1\s+100\.0%$",
                     _line(out, "carre"))
    # disco: 3 docs, rows for aceite+fideos+pan, only aceite is comparable
    assert re.search(r"^disco\s+3\s+3\s+1\s+33\.3%$",
                     _line(out, "disco"))
    # mami: 1 doc, the single-chain Coca row -> 0.0%
    assert re.search(r"^mami\s+1\s+1\s+0\s+0\.0%$", _line(out, "mami"))
    # hiper and chang carry no documents at all
    assert re.search(r"^hiper\s+0\s+0\s+0\s+0\.0%$", _line(out, "hiper"))
    assert re.search(r"^chang\s+0\s+0\s+0\s+0\.0%$", _line(out, "chang"))


def test_coverage_prints_both_blocks_with_the_category_block_first(
        coverage_collection, capsys):
    coverage_collection.documents = [dict(doc) for doc in _COVERAGE_DOCS]

    exit_code = cli.main(["coverage"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "por categoria" in out
    assert "por cadena" in out
    assert out.index("por categoria") < out.index("por cadena")


# -- run: wiring ----------------------------------------------------------------

def test_run_loads_env_file_without_default_and_passes_category_through(
        fake_env, monkeypatch):
    """``run`` keeps today's contract: the shell environment decides, so the
    helper is called with NO default — a run must never be silently
    retargeted at whatever ``.env`` (the production database) says. The
    selector still applies, and the category travels unchanged."""
    calls = []
    monkeypatch.setattr(
        cli, "load_env_file",
        lambda *args, **kwargs: calls.append(args) or None)
    monkeypatch.setenv("LALISTITA_ENV_FILE", "/tmp/irrelevant")

    fake_env.status = status_for(RunState.SUCCEEDED)
    assert cli.main(["run", "disco", "--category", "almacen"]) == 0
    assert calls == [()], "cmd_run must not pass a default env file"
    assert fake_env.started == [("disco", "almacen")]


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


# -- enrich-ean (ean-enrichment T4) --------------------------------------------


class FakeHTTPSession:
    """Offline stand-in for ``build_http_session``: canned detail pages.

    Records every URL and fails loudly on an unexpected request; the canned
    value can also be an exception, to drive the failure paths.
    """

    def __init__(self, pages):
        self.pages = dict(pages)
        self.urls: list[str] = []

    def get(self, url, timeout=None):
        self.urls.append(url)
        if url not in self.pages:
            raise AssertionError(f"unexpected GET: {url}")
        value = self.pages[url]
        if isinstance(value, Exception):
            raise value
        return SimpleNamespace(status_code=200, text=value)


@pytest.fixture
def enrich_env(monkeypatch):
    """Swap the CLI's database and HTTP seams for fakes.

    ``MongoProductRepository`` resolves to one ``InMemoryProductRepository``
    seeded per test; ``load_env_file`` is recorded (never reads a real env
    file) and must be called with NO default, same rule as ``run``.
    """
    env_calls: list[tuple[tuple, dict]] = []

    def record_env_file(*args, **kwargs):
        env_calls.append((args, kwargs))

    repo = InMemoryProductRepository()
    monkeypatch.setattr(cli, "load_env_file", record_env_file)
    monkeypatch.setattr(
        cli, "build_client",
        lambda settings: FakeMongoClient(settings.mongodb_uri, connect=False))
    monkeypatch.setattr(cli, "MongoProductRepository", lambda database: repo)
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    return repo, env_calls


def _detail_page(gtin):
    return ('<script type="application/ld+json">'
            '{"@type": "Product", "gtin": "%s"}'
            '</script>' % gtin)


def test_enrich_ean_parser_defaults(monkeypatch):
    captured = {}

    def fake_cmd(args):
        captured.update(vars(args))
        return 0

    monkeypatch.setattr(cli, "cmd_enrich_ean", fake_cmd)
    assert cli.main(["enrich-ean"]) == 0
    assert captured["chain"] == "laanonima"
    assert captured["limit"] == 0
    assert captured["sleep"] == 0.4


def test_enrich_ean_loads_the_env_file_with_no_default(enrich_env):
    repo, env_calls = enrich_env
    repo.replace_products("La Anónima", [])

    assert cli.main(["enrich-ean"]) == 0
    assert env_calls == [((), {})], \
        "enrich-ean must keep run's rule: no default env file"


def test_enrich_ean_unknown_chain_fails_loudly(capsys):
    exit_code = cli.main(["enrich-ean", "--chain", "supermami"])
    captured = capsys.readouterr()
    assert exit_code == 3
    assert "supermami" in captured.out + captured.err
    assert "laanonima" in captured.out + captured.err
    assert "Traceback" not in captured.out + captured.err


def test_enrich_ean_flow_calls_update_eans_with_the_service_mapping(
        enrich_env, monkeypatch, capsys):
    """The full offline flow: the CLI reads the chain's documents, fetches
    the detail pages of the empty-ean candidates through La Anónima's site
    knowledge, and writes through ``update_eans``."""
    repo, _ = enrich_env
    repo.replace_products("La Anónima", [
        {"name": "Coca", "price": 1.0, "sku": "3100001"},
        {"name": "Fanta", "price": 1.0, "sku": "3100002",
         "ean": "7790000000001"},   # never re-fetched, never overwritten
    ])
    repo.replace_products("Disco", [
        {"name": "Coca", "price": 1.0, "sku": "3100001"},  # another chain
    ])
    session = FakeHTTPSession({
        "https://www.laanonima.com.ar/x/art_3100001/":
            _detail_page("7790895000123"),
    })
    monkeypatch.setattr(cli, "build_http_session", lambda: session)

    assert cli.main(["enrich-ean"]) == 0
    out = capsys.readouterr().out
    assert session.urls == ["https://www.laanonima.com.ar/x/art_3100001/"]
    assert repo.update_ean_calls == [
        ("La Anónima", {"3100001": "7790895000123"})]
    stored = {doc["name"]: doc for doc in repo.find_all()
              if doc["supermercado"] == "La Anónima"}
    assert stored["Coca"]["ean"] == "7790895000123"
    assert stored["Fanta"]["ean"] == "7790000000001"
    assert "attempted: 1" in out
    assert "enriched: 1" in out
    assert "without_gtin: 0" in out
    assert "failed: 0" in out
    assert "modified: 1" in out


def test_enrich_ean_reports_a_page_without_gtin(enrich_env, monkeypatch,
                                                capsys):
    repo, _ = enrich_env
    repo.replace_products("La Anónima",
                          [{"name": "Coca", "price": 1.0, "sku": "3100001"}])
    # A category-shaped page: ItemList, no gtin anywhere.
    session = FakeHTTPSession({
        "https://www.laanonima.com.ar/x/art_3100001/":
            '<script type="application/ld+json">'
            '{"@type": "ItemList", "itemListElement": []}'
            '</script>',
    })
    monkeypatch.setattr(cli, "build_http_session", lambda: session)

    assert cli.main(["enrich-ean"]) == 0
    out = capsys.readouterr().out
    assert "attempted: 1" in out
    assert "without_gtin: 1" in out
    assert "modified: 0" in out
    assert repo.update_ean_calls == [("La Anónima", {})]


def test_enrich_ean_limit_bounds_the_candidates(enrich_env, monkeypatch):
    repo, _ = enrich_env
    repo.replace_products("La Anónima", [
        {"name": "a", "price": 1.0, "sku": "1"},
        {"name": "b", "price": 1.0, "sku": "2"},
        {"name": "c", "price": 1.0, "sku": "3"},
    ])
    session = FakeHTTPSession({
        "https://www.laanonima.com.ar/x/art_1/": _detail_page("7780000000011"),
        "https://www.laanonima.com.ar/x/art_2/": _detail_page("7780000000022"),
        "https://www.laanonima.com.ar/x/art_3/": _detail_page("7780000000033"),
    })
    monkeypatch.setattr(cli, "build_http_session", lambda: session)

    assert cli.main(["enrich-ean", "--limit", "2"]) == 0
    assert session.urls == [
        "https://www.laanonima.com.ar/x/art_1/",
        "https://www.laanonima.com.ar/x/art_2/",
    ]
    assert repo.update_ean_calls == [(
        "La Anónima", {"1": "7780000000011", "2": "7780000000022"})]


def test_enrich_ean_uses_the_sleep_option_between_requests(
        enrich_env, monkeypatch):
    """N-5: the operator's ``--sleep`` is the pause between detail-page
    requests; tests never actually sleep because the fixture neutralises
    ``time.sleep``."""
    repo, _ = enrich_env
    repo.replace_products("La Anónima", [
        {"name": "a", "price": 1.0, "sku": "1"},
        {"name": "b", "price": 1.0, "sku": "2"},
    ])
    session = FakeHTTPSession({
        "https://www.laanonima.com.ar/x/art_1/": _detail_page("7780000000011"),
        "https://www.laanonima.com.ar/x/art_2/": _detail_page("7780000000022"),
    })
    monkeypatch.setattr(cli, "build_http_session", lambda: session)
    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda seconds: slept.append(seconds))

    assert cli.main(["enrich-ean", "--sleep", "2.5"]) == 0
    assert slept == [2.5], "one pause between the two requests, none after"


def test_enrich_ean_repository_failure_returns_1(enrich_env, monkeypatch,
                                                 capsys):
    repo, _ = enrich_env
    repo.find_all_error = RepositoryUnavailable("server unreachable")

    exit_code = cli.main(["enrich-ean"])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "server unreachable" in captured.out + captured.err
