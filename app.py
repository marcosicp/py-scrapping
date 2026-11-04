"""Flask application entry point.

Two entry points share one factory:

    python app.py        local development (Werkzeug dev server)
    gunicorn main:app    WSGI servers; see main.py

Nothing the app needs is wired at import time, because a WSGI server imports this
module rather than running it. Wrapping the old setup in `if __name__ == '__main__'`
is exactly what made SocketIO and the Mongo handles absent in production (K-1, K-2).
"""

import os

from dotenv import load_dotenv
from flask import Flask
from flask_cors import CORS
from pymongo import MongoClient

from api.config import Settings
from api.routes import app_file2
from api.sockets import configure_sockets

# Load environment variables before `__main__` reads PORT (kept here so both
# entry points see .env; create_app itself reads the environment through
# Settings.from_env).
load_dotenv()


def _init_mongo(app: Flask, settings: Settings) -> Flask:
    """Attach a MongoClient and database handle to the app.

    This must run for every entry point. Routes and all five scrapers read
    `current_app.mongodb_client`, so skipping it under WSGI used to raise
    AttributeError.

    `MongoClient` connects lazily, so this does not open a socket and cannot make
    an import hang.

    The database name was previously set to "lalistita" here while every consumer
    read `lalistitadev`; the set value was therefore dead and misleading (K-3).
    """
    # connect=False defers the background server monitors to the first real
    # operation, so building the app never starts a connection attempt (this is
    # also what keeps the unroutable test URI inert).
    app.mongodb_client = MongoClient(settings.mongodb_uri, connect=False)
    app.database = app.mongodb_client[settings.mongodb_db]
    return app


def create_app(settings: Settings | None = None) -> Flask:
    """Build the Flask application.

    Called by `python app.py`, by `main:app` for WSGI servers, and by tests.
    With no explicit settings the configuration is read from the environment
    (`SECRET_KEY`, `MONGODB_URI`, `MONGODB_DB` — see `api.config.Settings`).
    """
    if settings is None:
        settings = Settings.from_env()

    app = Flask(__name__, static_url_path='')
    CORS(app)
    # Configurable, same default as before. A real rotation is K-13.
    app.config['SECRET_KEY'] = settings.secret_key

    app.register_blueprint(app_file2)

    configure_sockets(app)  # Initialize sockets for every entry point (K-1)
    _init_mongo(app, settings)  # Attach the database handles (K-2)

    return app


if __name__ == '__main__':
    port = int(os.getenv("PORT") or 3000)
    create_app().run(port=port, debug=True)
