"""``SocketIOReporter`` publishes runner progress on the Socket.IO channels."""
from datetime import datetime, timezone

import api.sockets
from api.sockets import SocketIOReporter
from api.services.scraping import RunState, RunStatus


def record_emissions(monkeypatch):
    calls = []
    monkeypatch.setattr(api.sockets.socketio, "emit",
                        lambda *args, **kwargs: calls.append((args, kwargs)))
    return calls


def test_message_emits_a_plain_string_on_the_legacy_channel(monkeypatch):
    calls = record_emissions(monkeypatch)
    SocketIOReporter().message("disco", "Descargando Disco")
    assert calls == [(("scraping-message-disco", "Descargando Disco"), {})]


def test_state_emits_the_status_snapshot_on_scraper_status(monkeypatch):
    calls = record_emissions(monkeypatch)
    status = RunStatus(
        slug="disco", label="Disco", state=RunState.RUNNING,
        category="almacen",
        started_at=datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc))
    SocketIOReporter().state(status)
    assert calls == [(("scraper-status", status.to_dict()), {})]


def test_the_reporter_satisfies_the_reporting_protocol():
    reporter = SocketIOReporter()
    assert callable(reporter.message)
    assert callable(reporter.state)
