"""SocketIO wiring for live scraper progress.

`notifyStatus` is a legacy shim kept until the scrapers report progress through
the scraper context (design D3); it is imported by the five scrapers, so its
signature must not change.

`configure_sockets(app)` initializes the singleton for every entry point.
"""

from flask_socketio import SocketIO

socketio = SocketIO()


def notifyStatus(paramText, paramValue):
    socketio.emit(paramText, paramValue)


def configure_sockets(app):
    socketio.init_app(app)
