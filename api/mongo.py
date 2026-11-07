"""MongoClient construction shared by every entry point (D-17/D-19).

pymongo validates TLS with the interpreter's default trust store. A python.org
build on macOS ships that store **empty** until ``Install Certificates.command``
runs — ``ssl.get_default_verify_paths()`` reports no cafile and
``.../etc/openssl/cert.pem`` does not exist — so every Atlas handshake dies with
``certificate verify failed: unable to get local issuer certificate``. ``requests``
never shows the symptom because it carries ``certifi`` itself, which is exactly
why scraping worked while the database did not (see
``odd/tasks/mongodb-tls-trust-store.md``).

The client therefore owns its bundle: certifi's for any TLS URI, or
``MONGODB_TLS_CA_FILE`` when an operator pins a private CA. Host behaviour stops
mattering: local, Docker and Render verify against the same roots.

Keeping one construction site also keeps ``connect=False`` in one place: building
the client must not open a socket, and the unroutable test URIs rely on it.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlsplit

import certifi
from pymongo import MongoClient

from api.config import Settings

# -- SRV URIs always mean TLS; the plain scheme has to ask for it
_TLS_SCHEME = "mongodb+srv"
_TLS_QUERY_KEYS = ("tls", "ssl")
_TLS_TRUE = {"true", "1"}


def uses_tls(uri: str) -> bool:
    """True when `uri` asks the driver for TLS (`+srv`, `tls=true`, `ssl=true`)."""
    parts = urlsplit(uri)
    if parts.scheme.lower() == _TLS_SCHEME:
        return True
    # -- keys are matched case-insensitively: ?TLS=True is the same request
    query = {key.lower(): values for key, values in parse_qs(parts.query).items()}
    for key in _TLS_QUERY_KEYS:
        for value in query.get(key, []):
            if value.strip().lower() in _TLS_TRUE:
                return True
    return False


def client_kwargs(settings: Settings) -> dict[str, Any]:
    """Keyword arguments for `MongoClient`, TLS trust included (D-17/D-18).

    A named `MONGODB_TLS_CA_FILE` always wins, even without a TLS URI: an
    operator who points at a bundle made an explicit decision. Otherwise only a
    TLS URI gets certifi's bundle, so `mongodb://localhost:27017/` keeps its old
    wiring untouched.
    """
    kwargs: dict[str, Any] = {"connect": False}
    if settings.mongodb_tls_ca_file:
        kwargs["tlsCAFile"] = settings.mongodb_tls_ca_file
    elif uses_tls(settings.mongodb_uri):
        kwargs["tlsCAFile"] = certifi.where()
    return kwargs


def build_client(settings: Settings) -> MongoClient:
    """Build the lazy client every entry point uses."""
    return MongoClient(settings.mongodb_uri, **client_kwargs(settings))
