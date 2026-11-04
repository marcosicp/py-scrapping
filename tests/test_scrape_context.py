"""Tests for ScrapeContext, the object every scraper talks to."""

import threading
import time

import pytest

from api.scrapers.base import ScrapeContext
from tests.fakes import InMemoryProductRepository


class ExplodingRepository:
    """Repository whose ``replace_products`` always fails."""

    def __init__(self):
        self.calls = []

    def find_all(self):
        return []

    def replace_products(self, supermercado, products, *,
                         categoria=None, subcategoria=None):
        self.calls.append((supermercado, categoria, subcategoria,
                           len(products)))
        raise RuntimeError("mongo is down")


class CloseRecorder:
    """Fake HTTP session / browser driver recording lifecycle calls."""

    def __init__(self, fail_close=False, fail_quit=False):
        self.close_calls = 0
        self.quit_calls = 0
        self._fail_close = fail_close
        self._fail_quit = fail_quit

    def close(self):
        self.close_calls += 1
        if self._fail_close:
            raise RuntimeError("close exploded")

    def quit(self):
        self.quit_calls += 1
        if self._fail_quit:
            raise RuntimeError("quit exploded")


def make_ctx(*, repository=None, reports=None, stop_event=None,
             browser_factory=None, http_factory=None):
    return ScrapeContext(
        slug="test",
        label="Test",
        category="almacen",
        stop_event=stop_event if stop_event is not None else threading.Event(),
        report=(reports if reports is not None else []).append,
        repository=repository if repository is not None
        else InMemoryProductRepository(),
        browser_factory=browser_factory,
        http_factory=http_factory,
    )


# -- reporting and stopping ---------------------------------------------


def test_report_forwards_to_the_callback():
    reports = []
    ctx = make_ctx(reports=reports)
    ctx.report("Scrapeando subcategoría: almacen")
    assert reports == ["Scrapeando subcategoría: almacen"]


def test_should_stop_follows_the_stop_event():
    ctx = make_ctx()
    assert ctx.should_stop() is False
    ctx._stop_event.set()
    assert ctx.should_stop() is True


# -- sleeping ------------------------------------------------------------


def test_sleep_returns_false_after_a_tiny_sleep():
    ctx = make_ctx()
    assert ctx.sleep(0.01) is False


def test_sleep_returns_true_immediately_when_stop_is_already_set():
    ctx = make_ctx()
    ctx._stop_event.set()
    start = time.monotonic()
    result = ctx.sleep(5)
    elapsed = time.monotonic() - start
    assert result is True
    assert elapsed < 1.0


def test_sleep_in_another_thread_returns_early_when_stop_is_set_mid_sleep():
    ctx = make_ctx()
    entered = threading.Event()
    outcome = {}

    def sleeper():
        entered.set()
        start = time.monotonic()
        outcome["result"] = ctx.sleep(30)
        outcome["elapsed"] = time.monotonic() - start

    thread = threading.Thread(target=sleeper, name="ctx-sleep-test")
    thread.start()
    try:
        assert entered.wait(5) is True
        ctx._stop_event.set()
        thread.join(5)
        assert not thread.is_alive()
        assert outcome["result"] is True
        assert outcome["elapsed"] < 1.0
    finally:
        ctx._stop_event.set()
        thread.join(5)


# -- saving through the repository ----------------------------------------


def test_save_delegates_to_repository_and_increments_saved():
    repository = InMemoryProductRepository()
    reports = []
    ctx = make_ctx(repository=repository, reports=reports)
    count = ctx.save([{"name": "pan", "price": 10}], categoria="almacen")
    assert count == 1
    assert repository.calls == [("Test", "almacen", None, 1)]
    assert ctx.saved == 1
    assert reports == ["Guardados 1 productos de almacen en base de datos"]


def test_save_reports_scope_preferring_subcategoria_then_categoria():
    repository = InMemoryProductRepository()
    reports = []
    ctx = make_ctx(repository=repository, reports=reports)
    ctx.save([{"name": "a"}], categoria="almacen", subcategoria="aceites")
    assert repository.calls == [("Test", "almacen", "aceites", 1)]
    assert reports == ["Guardados 1 productos de aceites en base de datos"]


def test_save_without_category_reports_the_label_as_scope():
    repository = InMemoryProductRepository()
    reports = []
    ctx = make_ctx(repository=repository, reports=reports)
    ctx.category = None
    count = ctx.save([{"name": "a"}, {"name": "b"}])
    assert count == 2
    assert reports == ["Guardados 2 productos de Test en base de datos"]


def test_save_with_empty_products_is_a_noop():
    repository = InMemoryProductRepository()
    reports = []
    ctx = make_ctx(repository=repository, reports=reports)
    assert ctx.save([], categoria="almacen") == 0
    assert repository.calls == []
    assert reports == []
    assert ctx.saved == 0


def test_save_survives_a_failing_repository():
    repository = ExplodingRepository()
    reports = []
    ctx = make_ctx(repository=repository, reports=reports)
    result = ctx.save([{"name": "a"}], categoria="almacen")
    assert result == 0
    assert ctx.saved == 0
    assert repository.calls == [("Test", "almacen", None, 1)]
    assert reports == ["Error al guardar almacen en base de datos"]


def test_save_failure_message_uses_subcategoria_scope():
    repository = ExplodingRepository()
    reports = []
    ctx = make_ctx(repository=repository, reports=reports)
    ctx.save([{"name": "a"}], categoria="almacen", subcategoria="snacks")
    assert reports == ["Error al guardar snacks en base de datos"]


# -- lazily built shared http session -------------------------------------


def test_http_is_built_lazily_exactly_once_and_closed_by_close():
    session = CloseRecorder()
    factory_calls = []

    def factory():
        factory_calls.append(1)
        return session

    ctx = make_ctx(http_factory=factory)
    assert factory_calls == []
    assert ctx.http is session
    assert ctx.http is session
    assert factory_calls == [1]
    assert session.close_calls == 0
    ctx.close()
    assert session.close_calls == 1


def test_close_is_safe_without_a_session():
    ctx = make_ctx()
    ctx.close()
    ctx.close()


def test_close_swallows_a_failing_session_close():
    ctx = make_ctx(
        http_factory=lambda: CloseRecorder(fail_close=True))
    assert ctx.http is not None
    ctx.close()  # must not raise


# -- browser context manager ----------------------------------------------


def test_browser_yields_the_factory_driver_and_quits():
    driver = CloseRecorder()
    ctx = make_ctx(browser_factory=lambda: driver)
    with ctx.browser() as yielded:
        assert yielded is driver
    assert driver.quit_calls == 1


def test_browser_quits_even_when_the_body_raises():
    driver = CloseRecorder()
    ctx = make_ctx(browser_factory=lambda: driver)
    with pytest.raises(ValueError):
        with ctx.browser():
            raise ValueError("scraper body failed")
    assert driver.quit_calls == 1


def test_browser_swallows_a_failing_quit():
    driver = CloseRecorder(fail_quit=True)
    ctx = make_ctx(browser_factory=lambda: driver)
    with ctx.browser():
        pass  # quit() raising inside the manager must not escape


def test_browser_without_factory_raises_runtime_error():
    ctx = make_ctx()
    with pytest.raises(RuntimeError) as excinfo:
        with ctx.browser():
            pass
    assert "no browser factory configured" in str(excinfo.value)
