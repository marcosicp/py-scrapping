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

from api.routes import app_file2
from api.sockets import configure_sockets

# Load environment variables
load_dotenv()

DEFAULT_MONGO_URI = "mongodb://localhost:27017/"
DEFAULT_MONGO_DB = "lalistitadev"


def _init_mongo(app: Flask) -> Flask:
    """Attach a MongoClient and database handle to the app.

    This must run for every entry point. Routes and all five scrapers read
    `current_app.mongodb_client`, so skipping it under WSGI used to raise
    AttributeError.

    `MongoClient` connects lazily, so this does not open a socket and cannot make
    an import hang.

    The database name was previously set to "lalistita" here while every consumer
    read `lalistitadev`; the set value was therefore dead and misleading (K-3).
    """
    uri = os.getenv("MONGODB_URI", DEFAULT_MONGO_URI)
    app.mongodb_client = MongoClient(uri)
    app.database = app.mongodb_client[os.getenv("MONGODB_DB", DEFAULT_MONGO_DB)]
    return app


def create_app() -> Flask:
    """Build the Flask application.

    Called by `python app.py`, by `main:app` for WSGI servers, and by tests.
    """
    app = Flask(__name__, static_url_path='')
    CORS(app)
    # Configurable, same default as before. A real rotation is K-13.
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'secret!')

    app.register_blueprint(app_file2)

    configure_sockets(app)  # Initialize sockets for every entry point (K-1)
    _init_mongo(app)        # Attach the database handles (K-2)

    return app


if __name__ == '__main__':
    port = int(os.getenv("PORT") or 3000)
    create_app().run(port=port, debug=True)
