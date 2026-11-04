"""Tests for ScraperManager: runs, single-flight, stop and reporting.

All fake scrapers synchronize with ``threading.Event`` handshakes and joins
with timeouts; ``time.sleep`` is never used for ordering.
"""

import contextlib
import threading

import pytest

from api.scrapers.base import BaseScraper
from api.scrapers.errors import (AlreadyRunning, InvalidCategory,
                                 NotRunning, UnknownScraper)
from api.scrapers.registry import ScraperRegistry
from api.services.scraping import (RunState, RunStatus, ScraperManager)
from tests.fakes import InMemoryProductRepository

TIMEOUT = 5.0


class RecordingReporter:
    def __init__(self):
        self.messages = []
        self.states = []
        self.fail = False

    def message(self, slug, text):
        if self.fail:
            raise RuntimeError("reporter is down")
        self.messages.append((slug, text))

    def state(self, status):
        if self.fail:
            raise RuntimeError("reporter is down")
        self.states.append(status)


class Happy(BaseScraper):
    slug = "happy"
    label = "Happy"

    def run(self, ctx):
        ctx.report("scanning")
        ctx.save([{"name": "pan", "price": 10}])


class Categorized(BaseScraper):
    slug = "categorized"
    label = "Categorized"
    categories = ("almacen", "bebidas")

    def run(self, ctx):
        ctx.report(f"category={ctx.category}")


class Failing(BaseScraper):
    slug = "failing"
    label = "Failing"

    def run(self, ctx):
        ctx.report("about to fail")
        raise ValueError("boom")


def make_loopy():
    entered = threading.Event()

    class Loopy(BaseScraper):
        slug = "loopy"
        label = "Loopy"

        def run(self, ctx):
            entered.set()
            while not ctx.should_stop():
                ctx.sleep(0.01)

    return Loopy, entered


def make_sleeper(seconds=30):
    entered = threading.Event()

    class Sleeper(BaseScraper):
        slug = "sleeper"
        label = "Sleeper"

        def run(self, ctx):
            entered.set()
            ctx.sleep(seconds)

    return Sleeper, entered


def make_restartable():
    saves = [True]

    class Restartable(BaseScraper):
        slug = "restartable"
        label = "Restartable"

        def run(self, ctx):
            if saves[0]:
                ctx.report("first run")
                ctx.save([{"name": f"p{i}"} for i in range(3)])
            else:
                ctx.report("second run")

    return Restartable, saves


def build(registry, repository=None, reporter=None):
    return ScraperManager(
        registry,
        repository if repository is not None else InMemoryProductRepository(),
        reporter=reporter,
    )


# -- listing, status and unknown slugs ------------------------------------


def test_list_gives_idle_for_every_registered_scraper_in_order():
    manager = build(ScraperRegistry([Happy, Failing]))
    statuses = manager.list()
    assert [s.slug for s in statuses] == ["happy", "failing"]
    assert all(s.state is RunState.IDLE for s in statuses)
    assert all(s.active is False for s in statuses)


def test_manager_exposes_the_registry():
    registry = ScraperRegistry([Happy])
    assert build(registry).registry is registry


def test_unknown_slug_raises_for_every_operation():
    manager = build(ScraperRegistry())
    with pytest.raises(UnknownScraper):
        manager.status("ghost")
    with pytest.raises(UnknownScraper):
        manager.start("ghost")
    with pytest.raises(UnknownScraper):
        manager.stop("ghost")
    with pytest.raises(UnknownScraper):
        manager.wait("ghost")


# -- starting, threading and success ---------------------------------------


def test_start_returns_running_at_once_and_runs_on_worker_thread():
    registry = ScraperRegistry([Happy])
    repository = InMemoryProductRepository()
    manager = build(registry, repository)

    status = manager.start("happy")
    assert status.state is RunState.RUNNING
    assert status.active is True
    assert status.started_at is not None
    assert status.slug == "happy"
    assert status.label == "Happy"

    final = manager.wait("happy", TIMEOUT)
    assert final.state is RunState.SUCCEEDED
    assert final.finished_at is not None
    assert final.saved == 1
    assert repository.calls == [("Happy", None, None, 1)]


def test_worker_runs_on_a_thread_named_scraper_slug_not_the_test_thread():
    main_thread = threading.current_thread()
    seen = {}

    class ThreadProbe(BaseScraper):
        slug = "probe"
        label = "Probe"

        def run(self, ctx):
            seen["name"] = threading.current_thread().name
            seen["is_main"] = threading.current_thread() is main_thread

    manager = build(ScraperRegistry([ThreadProbe]))
    manager.start("probe")
    final = manager.wait("probe", TIMEOUT)
    assert final.state is RunState.SUCCEEDED
    assert seen["name"] == "scraper-probe"
    assert seen["is_main"] is False


def test_worker_thread_is_daemon_and_joined_by_wait():
    manager = build(ScraperRegistry([Happy]))
    manager.start("happy")
    manager.wait("happy", TIMEOUT)
    leaked = [t for t in threading.enumerate()
              if t.name.startswith("scraper-")]
    assert leaked == []


def test_success_sets_saved_and_reports_default_http_is_built():
    # Happy does not touch ctx.http; a None http_factory must still work.
    manager = build(ScraperRegistry([Happy]))
    manager.start("happy")
    assert manager.wait("happy", TIMEOUT).state is RunState.SUCCEEDED


# -- single-flight and concurrency -----------------------------------------


def test_second_start_of_same_slug_while_running_raises_already_running():
    Loopy, entered = make_loopy()
    manager = build(ScraperRegistry([Loopy]))
    try:
        manager.start("loopy")
        assert entered.wait(TIMEOUT) is True
        with pytest.raises(AlreadyRunning) as excinfo:
            manager.start("loopy")
        assert excinfo.value.slug == "loopy"
    finally:
        manager.stop("loopy")
        manager.wait("loopy", TIMEOUT)


def test_two_different_slugs_run_concurrently():
    LoopyA, entered_a = make_loopy()
    LoopyB, entered_b = make_loopy()

    class LoopyA2(LoopyA):
        slug = "loop-a"
        label = "LoopA"

    class LoopyB2(LoopyB):
        slug = "loop-b"
        label = "LoopB"

    manager = build(ScraperRegistry([LoopyA2, LoopyB2]))
    try:
        manager.start("loop-a")
        manager.start("loop-b")
        assert entered_a.wait(TIMEOUT) is True
        assert entered_b.wait(TIMEOUT) is True
        assert manager.status("loop-a").state is RunState.RUNNING
        assert manager.status("loop-b").state is RunState.RUNNING
    finally:
        manager.stop("loop-a")
        manager.stop("loop-b")
        manager.wait("loop-a", TIMEOUT)
        manager.wait("loop-b", TIMEOUT)


# -- failure and restart ----------------------------------------------------


def test_failure_marks_failed_with_error_message_and_allows_restart():
    reports = RecordingReporter()
    manager = build(ScraperRegistry([Failing]), reporter=reports)
    manager.start("failing")
    final = manager.wait("failing", TIMEOUT)
    assert final.state is RunState.FAILED
    assert final.finished_at is not None
    assert final.message is not None and "boom" in final.message
    assert ("failing", "ERROR: ValueError: boom") in reports.messages
    # The same slug can be started again after a failure.
    again = manager.start("failing")
    assert again.state is RunState.RUNNING
    manager.wait("failing", TIMEOUT)


def test_restart_resets_saved_and_message():
    Restartable, saves = make_restartable()
    manager = build(ScraperRegistry([Restartable]))
    manager.start("restartable")
    first = manager.wait("restartable", TIMEOUT)
    assert first.state is RunState.SUCCEEDED
    assert first.saved == 3
    saves[0] = False
    manager.start("restartable")
    second = manager.wait("restartable", TIMEOUT)
    assert second.state is RunState.SUCCEEDED
    # A fresh run resets the message and the saved counter.
    assert second.saved == 0
    assert second.message == "second run"


# -- cooperative stop --------------------------------------------------------


def test_stop_marks_stopping_then_run_ends_stopped():
    Loopy, entered = make_loopy()
    manager = build(ScraperRegistry([Loopy]))
    try:
        manager.start("loopy")
        assert entered.wait(TIMEOUT) is True
        after_stop = manager.stop("loopy")
        assert after_stop.state is RunState.STOPPING
        assert after_stop.active is True
        final = manager.wait("loopy", TIMEOUT)
        assert final.state is RunState.STOPPED
        assert final.finished_at is not None
    finally:
        # The run may already be over; stop() would raise NotRunning.
        with contextlib.suppress(Exception):
            manager.stop("loopy")
        manager.wait("loopy", TIMEOUT)


def test_stop_cannot_interrupt_twice_and_is_idempotent_once_stopping():
    Loopy, entered = make_loopy()
    manager = build(ScraperRegistry([Loopy]))
    try:
        manager.start("loopy")
        assert entered.wait(TIMEOUT) is True
        first = manager.stop("loopy")
        second = manager.stop("loopy")  # already STOPPING: idempotent
        assert second.state is RunState.STOPPING
        assert first.state is RunState.STOPPING
        manager.wait("loopy", TIMEOUT)
    finally:
        manager.wait("loopy", TIMEOUT)


def test_stop_interrupts_a_blocker_sleep_immediately():
    Sleeper, entered = make_sleeper(30)
    manager = build(ScraperRegistry([Sleeper]))
    try:
        manager.start("sleeper")
        assert entered.wait(TIMEOUT) is True
        manager.stop("sleeper")
        final = manager.wait("sleeper", TIMEOUT)
        assert final.state is RunState.STOPPED
    finally:
        # The run may already be over; stop() would raise NotRunning.
        with contextlib.suppress(Exception):
            manager.stop("sleeper")
        manager.wait("sleeper", TIMEOUT)


def test_stop_when_idle_or_finished_raises_not_running():
    manager = build(ScraperRegistry([Happy]))
    with pytest.raises(NotRunning) as excinfo:
        manager.stop("happy")
    assert excinfo.value.slug == "happy"
    manager.start("happy")
    manager.wait("happy", TIMEOUT)
    with pytest.raises(NotRunning):
        manager.stop("happy")


# -- validation and context wiring -------------------------------------------


def test_invalid_category_raises_and_nothing_starts():
    manager = build(ScraperRegistry([Categorized]))
    with pytest.raises(InvalidCategory) as excinfo:
        manager.start("categorized", category="nope")
    assert excinfo.value.slug == "categorized"
    assert excinfo.value.category == "nope"
    assert excinfo.value.allowed == ("almacen", "bebidas")
    assert manager.status("categorized").state is RunState.IDLE


def test_category_is_passed_to_status_and_context():
    seen = {}

    class CategoryProbe(Categorized):
        slug = "category-probe"
        label = "CategoryProbe"
        categories = ("almacen", "bebidas")

        def run(self, ctx):
            seen["category"] = ctx.category

    probe_registry = ScraperRegistry([CategoryProbe])
    manager = build(probe_registry)
    status = manager.start("category-probe", category="bebidas")
    assert status.category == "bebidas"
    manager.wait("category-probe", TIMEOUT)
    assert seen["category"] == "bebidas"


# -- reporter contract ---------------------------------------------------------


def test_reporter_receives_messages_and_running_to_succeeded_states():
    reports = RecordingReporter()
    manager = build(ScraperRegistry([Happy]), reporter=reports)
    manager.start("happy")
    manager.wait("happy", TIMEOUT)
    texts = [text for slug, text in reports.messages if slug == "happy"]
    assert "scanning" in texts
    assert "Guardados 1 productos de Happy en base de datos" in texts
    states = [s.state.value for s in reports.states if s.slug == "happy"]
    assert states == ["running", "succeeded"]


def test_a_broken_reporter_never_breaks_the_run():
    reports = RecordingReporter()
    reports.fail = True
    manager = build(ScraperRegistry([Happy]), reporter=reports)
    manager.start("happy")
    final = manager.wait("happy", TIMEOUT)
    assert final.state is RunState.SUCCEEDED


# -- stress ----------------------------------------------------------------------


def test_start_stop_stress_twenty_cycles_no_leaked_threads():
    Loopy, entered = make_loopy()
    manager = build(ScraperRegistry([Loopy]))
    try:
        for _ in range(20):
            manager.start("loopy")
            manager.stop("loopy")
            final = manager.wait("loopy", TIMEOUT)
            assert final.state is RunState.STOPPED
    finally:
        manager.wait("loopy", TIMEOUT)
    leaked = [t for t in threading.enumerate()
              if t.name.startswith("scraper-")]
    assert leaked == []


def test_start_stop_stress_final_state_consistent():
    Loopy, entered = make_loopy()
    manager = build(ScraperRegistry([Loopy]))
    for _ in range(20):
        manager.start("loopy")
        manager.stop("loopy")
        final = manager.wait("loopy", TIMEOUT)
        assert final.state in (RunState.STOPPED,)
    assert manager.status("loopy").state is RunState.STOPPED


# -- defect 1: versioned, ordered state delivery --------------------------


def test_deliver_state_drops_stale_versions():
    reports = RecordingReporter()
    manager = build(ScraperRegistry([Happy]), reporter=reports)

    running = RunStatus(slug="happy", label="Happy", state=RunState.RUNNING)
    done = RunStatus(slug="happy", label="Happy", state=RunState.SUCCEEDED)
    manager._deliver_state("happy", 2, done)
    manager._deliver_state("happy", 1, running)  # stale: dropped
    assert [s.state for s in reports.states] == [RunState.SUCCEEDED]

    # A later higher version is delivered again.
    failed = RunStatus(slug="happy", label="Happy", state=RunState.FAILED)
    manager._deliver_state("happy", 3, failed)
    assert ([s.state for s in reports.states]
            == [RunState.SUCCEEDED, RunState.FAILED])

    # A different slug has an independent version counter.
    other = RunStatus(slug="failing", label="Failing", state=RunState.RUNNING)
    manager._deliver_state("failing", 1, other)
    assert [s.slug for s in reports.states] == ["happy", "happy", "failing"]


def make_gated(identifier, raises=False):
    """A scraper parked in ``run()`` until released, so state notifications
    can be observed deterministically before its final state is computed."""
    entered = threading.Event()
    release = threading.Event()

    class Gated(BaseScraper):
        slug = f"gated-{identifier}"
        label = f"Gated{identifier}"

        def run(self, ctx):
            entered.set()
            release.wait(TIMEOUT)
            if raises:
                raise ValueError("boom")

    return Gated, entered, release


def test_state_sequence_running_then_succeeded_is_exact():
    Gated, entered, release = make_gated("ok")
    reports = RecordingReporter()
    manager = build(ScraperRegistry([Gated]), reporter=reports)
    try:
        # start() delivers 'running' synchronously; the worker is parked, so
        # it cannot overtake with the final state.
        manager.start("gated-ok")
        assert entered.wait(TIMEOUT) is True
        release.set()
        final = manager.wait("gated-ok", TIMEOUT)
        assert final.state is RunState.SUCCEEDED
        states = [s.state.value for s in reports.states
                  if s.slug == "gated-ok"]
        assert states == ["running", "succeeded"]
    finally:
        release.set()
        manager.wait("gated-ok", TIMEOUT)


def test_state_sequence_for_a_stopped_run_is_exact():
    entered = threading.Event()
    parked = threading.Event()
    leaving = threading.Event()

    class GatedLooper(BaseScraper):
        slug = "gated-looper"
        label = "GatedLooper"

        def run(self, ctx):
            entered.set()
            while not ctx.should_stop():
                ctx.sleep(0.01)
            # Park before returning: STOPPING must be observed while the
            # worker is still inside, before its final-state bump.
            parked.set()
            leaving.wait(TIMEOUT)

    reports = RecordingReporter()
    manager = build(ScraperRegistry([GatedLooper]), reporter=reports)
    try:
        manager.start("gated-looper")
        assert entered.wait(TIMEOUT) is True
        manager.stop("gated-looper")  # delivers STOPPING synchronously
        assert parked.wait(TIMEOUT) is True
        states = [s.state.value for s in reports.states
                  if s.slug == "gated-looper"]
        assert states == ["running", "stopping"]
        leaving.set()
        final = manager.wait("gated-looper", TIMEOUT)
        assert final.state is RunState.STOPPED
        states = [s.state.value for s in reports.states
                  if s.slug == "gated-looper"]
        assert states == ["running", "stopping", "stopped"]
    finally:
        leaving.set()
        manager.wait("gated-looper", TIMEOUT)


def test_state_sequence_for_a_failing_run_is_exact():
    Gated, entered, release = make_gated("fail", raises=True)
    reports = RecordingReporter()
    manager = build(ScraperRegistry([Gated]), reporter=reports)
    try:
        manager.start("gated-fail")
        assert entered.wait(TIMEOUT) is True
        release.set()
        final = manager.wait("gated-fail", TIMEOUT)
        assert final.state is RunState.FAILED
        states = [s.state.value for s in reports.states
                  if s.slug == "gated-fail"]
        assert states == ["running", "failed"]
    finally:
        release.set()
        manager.wait("gated-fail", TIMEOUT)


def test_reentrant_reporter_does_not_deadlock():
    _Gated, _entered, release = make_gated("reentrant")

    class LateBound:
        """Reporter wired to the manager after construction, whose callback
        re-enters the manager."""

        def __init__(self):
            self.target = None

        def message(self, slug, text):
            pass

        def state(self, status):
            self.target.status(status.slug)
            self.target.list()

    reporter = LateBound()
    manager = build(ScraperRegistry([_Gated]), reporter=reporter)
    reporter.target = manager
    try:
        start_status = manager.start("gated-reentrant")
        assert start_status.state is RunState.RUNNING
        release.set()
        final = manager.wait("gated-reentrant", TIMEOUT)
        assert final.state is RunState.SUCCEEDED
    finally:
        release.set()
        manager.wait("gated-reentrant", TIMEOUT)


# -- defect 2: a BaseException exit still reaches a terminal state ---------


class SystemExitScraper(BaseScraper):
    slug = "sysx"
    label = "SysExitScraper"

    def run(self, ctx):
        raise SystemExit(1)


@pytest.mark.filterwarnings(
    "ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_base_exception_ends_failed_and_frees_the_slug():
    reports = RecordingReporter()
    manager = build(ScraperRegistry([SystemExitScraper]), reporter=reports)
    manager.start("sysx")
    final = manager.wait("sysx", TIMEOUT)
    assert final.state is RunState.FAILED
    assert final.finished_at is not None
    # The slug is usable again: no ghost RUNNING record.
    again = manager.start("sysx")
    assert again.state is RunState.RUNNING
    assert manager.wait("sysx", TIMEOUT).state is RunState.FAILED
    states = [s.state.value for s in reports.states if s.slug == "sysx"]
    assert states == ["running", "failed", "running", "failed"]


# -- defect 3: thread.start() failure leaves no ghost RUNNING record -------


def test_thread_start_failure_leaves_no_ghost_running_record(monkeypatch):
    manager = build(ScraperRegistry([Happy]))

    def boom(self):
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(threading.Thread, "start", boom)
    with pytest.raises(RuntimeError, match="can't start new thread"):
        manager.start("happy")
    # No ghost record: the slug is IDLE again.
    assert manager.status("happy").state is RunState.IDLE

    with pytest.raises(RuntimeError, match="can't start new thread"):
        manager.start("happy")
    assert manager.status("happy").state is RunState.IDLE

    # Undo the patch: the same slug starts normally now.
    monkeypatch.undo()
    manager.start("happy")
    final = manager.wait("happy", TIMEOUT)
    assert final.state is RunState.SUCCEEDED


def test_thread_start_failure_keeps_previous_finished_state(monkeypatch):
    repository = InMemoryProductRepository()
    manager = build(ScraperRegistry([Happy]), repository=repository)
    manager.start("happy")
    first = manager.wait("happy", TIMEOUT)
    assert first.state is RunState.SUCCEEDED

    def boom(self):
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(threading.Thread, "start", boom)
    with pytest.raises(RuntimeError, match="can't start new thread"):
        manager.start("happy")
    # The previous FINISHED run is what remains, not a ghost RUNNING one.
    assert manager.status("happy").state is RunState.SUCCEEDED
    monkeypatch.undo()
    again = manager.start("happy")
    assert again.state is RunState.RUNNING
    assert manager.wait("happy", TIMEOUT).state is RunState.SUCCEEDED
