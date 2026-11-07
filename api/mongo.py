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
mattering: local, Docker and Render verify against the same roots. A URI that
names its own bundle (``tlsCAFile``, ``tls_ca_file``, ``ssl_ca_certs``) is left
alone: injecting a second one would override or shadow the operator's choice, so
the precedence is URI, then ``MONGODB_TLS_CA_FILE``, then certifi (R3-001).

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
# -- query spellings pymongo accepts for a CA bundle; a URI carrying one wins
_CA_QUERY_KEYS = ("tlscafile", "tls_ca_file", "ssl_ca_certs")


def _query(uri: str) -> dict[str, list[str]]:
    """Lower-cased query parameters, so ?TLS=True and ?tls=true agree."""
    return {key.lower(): values
            for key, values in parse_qs(urlsplit(uri).query).items()}


def uri_tls_ca_file(uri: str) -> str | None:
    """CA bundle the URI itself names, if any (`tlsCAFile` and its aliases)."""
    query = _query(uri)
    for key in _CA_QUERY_KEYS:
        values = query.get(key)
        if values and values[-1].strip():
            return values[-1].strip()
    return None


def uses_tls(uri: str) -> bool:
    """True when `uri` asks the driver for TLS (`+srv`, `tls=true`, `ssl=true`)."""
    if urlsplit(uri).scheme.lower() == _TLS_SCHEME:
        return True
    query = _query(uri)
    for key in _TLS_QUERY_KEYS:
        for value in query.get(key, []):
            if value.strip().lower() in _TLS_TRUE:
                return True
    return False


def client_kwargs(settings: Settings) -> dict[str, Any]:
    """Keyword arguments for `MongoClient`, TLS trust included (D-17/D-18).

    Precedence (R3-001): the URI's own bundle first, then a named
    `MONGODB_TLS_CA_FILE`, then certifi for a TLS URI. A URI that already pins a
    bundle gets no injected option at all — pymongo reads the URI's value, so a
    second one would at best be dead code and at worst shadow the operator's
    choice. `mongodb://localhost:27017/` keeps its old wiring untouched.
    """
    kwargs: dict[str, Any] = {"connect": False}
    if uri_tls_ca_file(settings.mongodb_uri):
        return kwargs
    if settings.mongodb_tls_ca_file:
        kwargs["tlsCAFile"] = settings.mongodb_tls_ca_file
    elif uses_tls(settings.mongodb_uri):
        kwargs["tlsCAFile"] = certifi.where()
    return kwargs


def build_client(settings: Settings) -> MongoClient:
    """Build the lazy client every entry point uses."""
    return MongoClient(settings.mongodb_uri, **client_kwargs(settings))
