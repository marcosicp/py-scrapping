"""SocketIO wiring for live scraper progress.

`SocketIOReporter` is the ProgressReporter the runner reports through: it
emits the same `scraping-message-<slug>` channel (plain string payload) and
the aggregated `scraper-status` snapshots.

`configure_sockets(app)` initializes the singleton for every entry point.
"""

from typing import TYPE_CHECKING

from flask_socketio import SocketIO

if TYPE_CHECKING:
    from api.services.scraping import RunStatus

socketio = SocketIO()


def configure_sockets(app):
    socketio.init_app(app)


class SocketIOReporter:
    """Publishes runner progress over the shared ``socketio`` singleton."""

    def message(self, slug: str, text: str) -> None:
        socketio.emit(f"scraping-message-{slug}", text)

    def state(self, status: "RunStatus") -> None:
        socketio.emit("scraper-status", status.to_dict())
