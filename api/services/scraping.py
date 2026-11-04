"""Per-supermarket run management (D4).

``ScraperManager`` owns the lifecycle of every scraper run: one active run
per supermarket, cooperative stop through a per-run ``threading.Event``,
status snapshots and progress reporting. No Flask, Mongo or SocketIO here —
the reporter is a seam the API layer plugs into (T5) and the CLI uses a
plain ``NullReporter``.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol

from api.repositories.products import ProductRepository
from api.scrapers.base import BaseScraper, ScrapeContext
from api.scrapers.http import build_http_session
from api.scrapers.errors import AlreadyRunning, NotRunning
from api.scrapers.registry import ScraperRegistry

logger = logging.getLogger(__name__)

Clock = Callable[[], datetime]


class RunState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    STOPPING = "stopping"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    STOPPED = "stopped"


ACTIVE_STATES = (RunState.RUNNING, RunState.STOPPING)


@dataclass(frozen=True)
class RunStatus:
    """Immutable snapshot of one scraper run."""

    slug: str
    label: str
    state: RunState = RunState.IDLE
    category: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    message: str | None = None
    saved: int = 0

    @property
    def active(self) -> bool:
        return self.state in ACTIVE_STATES

    def to_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "label": self.label,
            "state": self.state.value,
            "active": self.active,
            "category": self.category,
            "started_at": (self.started_at.isoformat()
                           if self.started_at is not None else None),
            "finished_at": (self.finished_at.isoformat()
                            if self.finished_at is not None else None),
            "message": self.message,
            "saved": self.saved,
        }


class ProgressReporter(Protocol):
    """Sink for scraper progress; every call must be safe to fail."""

    def message(self, slug: str, text: str) -> None:
        ...

    def state(self, status: RunStatus) -> None:
        ...


class NullReporter:
    """Reporter that discards everything."""

    def message(self, slug: str, text: str) -> None:
        pass

    def state(self, status: RunStatus) -> None:
        pass


class _Run:
    """Mutable per-slug internal run record."""

    __slots__ = ("label", "state", "category", "started_at", "finished_at",
                 "message", "stop_event", "thread", "ctx")

    def __init__(self, label: str) -> None:
        self.label = label
        self.state: RunState = RunState.IDLE
        self.category: str | None = None
        self.started_at: datetime | None = None
        self.finished_at: datetime | None = None
        self.message: str | None = None
        self.stop_event: threading.Event | None = None
        self.thread: threading.Thread | None = None
        self.ctx: ScrapeContext | None = None


class ScraperManager:
    """Runs one supermarket scraper at a time, per slug."""

    def __init__(self, registry: ScraperRegistry,
                 repository: ProductRepository, *,
                 reporter: ProgressReporter | None = None,
                 browser_factory: Callable[[], Any] | None = None,
                 http_factory: Callable[[], Any] | None = None,
                 clock: Clock | None = None) -> None:
        self._registry = registry
        self._repository = repository
        self._reporter: ProgressReporter = (reporter if reporter is not None
                                            else NullReporter())
        self._browser_factory = browser_factory
        self._http_factory = (http_factory if http_factory is not None
                              else build_http_session)
        self._clock = (clock if clock is not None
                       else (lambda: datetime.now(timezone.utc)))
        self._lock = threading.RLock()
        # Separate lock for state notifications: RLock so a reporter that
        # calls back into the manager cannot deadlock.
        self._notify_lock = threading.RLock()
        # Monotonically increasing state versions per slug; never reset
        # between runs. The delivered version drops out-of-order or stale
        # notifications so the UI never regresses to an older state.
        self._versions: dict[str, int] = {}
        self._delivered: dict[str, int] = {}
        self._runs: dict[str, _Run] = {}

    @property
    def registry(self) -> ScraperRegistry:
        return self._registry

    # -- queries -----------------------------------------------------------------

    def list(self) -> list[RunStatus]:
        """One status per registered scraper, in registry order."""
        with self._lock:
            return [self._snapshot(slug) for slug in self._registry.slugs()]

    def status(self, slug: str) -> RunStatus:
        """The current status of ``slug``; IDLE if it never started."""
        with self._lock:
            self._registry.get(slug)
            return self._snapshot(slug)

    def wait(self, slug: str, timeout: float | None = None) -> RunStatus:
        """Join the worker thread (if any) and return the status."""
        with self._lock:
            self._registry.get(slug)
            record = self._runs.get(slug)
            thread = record.thread if record is not None else None
        if thread is not None:
            thread.join(timeout)
        return self.status(slug)

    # -- lifecycle -----------------------------------------------------------------

    def start(self, slug: str, category: str | None = None) -> RunStatus:
        """Start a run of ``slug`` unless one is already active."""
        # Validation happens before touching any run state.
        cls = self._registry.get(slug)
        category = cls.validate_category(category)

        with self._lock:
            record = self._runs.get(slug)
            if record is not None and record.state in ACTIVE_STATES:
                raise AlreadyRunning(slug)

            stop_event = threading.Event()
            ctx = ScrapeContext(
                slug=slug,
                label=cls.label,
                category=category,
                stop_event=stop_event,
                report=self._make_reporter_callback(slug),
                repository=self._repository,
                browser_factory=self._browser_factory,
                http_factory=self._http_factory,
            )
            thread = threading.Thread(target=self._worker,
                                      args=(slug, cls, ctx, stop_event),
                                      name=f"scraper-{slug}", daemon=True)
            record = _Run(cls.label)
            record.state = RunState.RUNNING
            record.category = category
            record.started_at = self._clock()
            record.stop_event = stop_event
            record.thread = thread
            record.ctx = ctx
            previous = self._runs.get(slug)
            self._runs[slug] = record
            try:
                thread.start()
            except BaseException:
                # Starting the thread failed (e.g. "can't start new thread"):
                # do not leave a ghost RUNNING record behind.
                if previous is None:
                    self._runs.pop(slug, None)
                else:
                    self._runs[slug] = previous
                raise
            version = self._bump(slug)
            snapshot = self._snapshot(slug)

        # Reporter calls happen outside the lock and never break a run.
        self._deliver_state(slug, version, snapshot)
        return snapshot

    def stop(self, slug: str) -> RunStatus:
        """Request cooperative stop for an active run of ``slug``."""
        with self._lock:
            self._registry.get(slug)  # UnknownScraper for unregistered slugs
            record = self._runs.get(slug)
            if (record is None
                    or record.stop_event is None
                    or record.state not in ACTIVE_STATES):
                raise NotRunning(slug)
            record.stop_event.set()
            if record.state is RunState.RUNNING:
                record.state = RunState.STOPPING
            version = self._bump(slug)
            snapshot = self._snapshot(slug)

        self._deliver_state(slug, version, snapshot)
        return snapshot

    # -- internals ---------------------------------------------------------------------

    def _make_reporter_callback(self, slug: str) -> Callable[[str], None]:
        def report(text: str) -> None:
            with self._lock:
                record = self._runs.get(slug)
                if record is not None:
                    record.message = text
            # Outside the lock: a slow or broken reporter never blocks a run.
            try:
                self._reporter.message(slug, text)
            except Exception:
                logger.warning("Progress reporter failed for '%s'", slug,
                               exc_info=True)
        return report

    def _bump(self, slug: str) -> int:
        """Next state version for ``slug``; caller holds ``self._lock``."""
        version = self._versions.get(slug, 0) + 1
        self._versions[slug] = version
        return version

    def _deliver_state(self, slug: str, version: int,
                       snapshot: RunStatus) -> None:
        """Deliver a state notification, dropping stale versions.

        Serialized through ``self._notify_lock`` (never ``self._lock``, so a
        re-entrant reporter cannot deadlock); a notification older than the
        last delivered one is silently dropped and never reaches the UI.
        """
        with self._notify_lock:
            if version <= self._delivered.get(slug, 0):
                return
            self._delivered[slug] = version
            try:
                self._reporter.state(snapshot)
            except Exception:
                logger.warning("Progress reporter failed for '%s'", slug,
                               exc_info=True)

    def _worker(self, slug: str, cls: type[BaseScraper], ctx: ScrapeContext,
                stop_event: threading.Event) -> None:
        # The terminal state is always recorded in ``finally``, so even a
        # BaseException (SystemExit, KeyboardInterrupt) cannot leave the run
        # stuck as RUNNING forever.
        final_state = RunState.FAILED
        try:
            cls().run(ctx)
            final_state = (RunState.STOPPED if stop_event.is_set()
                           else RunState.SUCCEEDED)
        except Exception as exc:
            logger.exception("Scraper '%s' failed", slug)
            message = f"{type(exc).__name__}: {exc}"
            ctx.report(f"ERROR: {message}")
        finally:
            try:
                ctx.close()
            except Exception:
                logger.warning("Failed to close the context of '%s'", slug,
                               exc_info=True)
            with self._lock:
                record = self._runs.get(slug)
                if record is not None:
                    record.state = final_state
                    record.finished_at = self._clock()
                    version = self._bump(slug)
                    snapshot = self._snapshot(slug)
                else:
                    version, snapshot = None, None
            if snapshot is not None:
                # A BaseException keeps propagating after the notification.
                self._deliver_state(slug, version, snapshot)

    def _snapshot(self, slug: str) -> RunStatus:
        # Caller holds self._lock.
        record = self._runs.get(slug)
        if record is None:
            cls = self._registry.get(slug)
            return RunStatus(slug=slug, label=cls.label)
        return RunStatus(
            slug=slug,
            label=record.label,
            state=record.state,
            category=record.category,
            started_at=record.started_at,
            finished_at=record.finished_at,
            message=record.message,
            saved=record.ctx.saved if record.ctx is not None else 0,
        )
