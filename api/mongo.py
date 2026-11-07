"""MongoClient construction shared by every entry point (D-17/D-19).

pymongo validates TLS with the interpreter's default trust store. A python.org
build on macOS ships that store **empty** until ``Install Certificates.command``
runs — ``ssl.get_default_verify_paths()`` reports no cafile and
``.../etc/openssl/cert.pem`` does not exist — so every Atlas handshake dies with
``certificate verify failed: unable to get local issuer certificate``. ``requests``
never shows the symptom because it carries ``certifi`` itself, which is exactly
why scraping worked while the database did not (see
``odd/tasks/mongodb-tls-trust-store.md``).

The client therefore owns its bundle: certifi's when the interpreter has no
host store, or ``MONGODB_TLS_CA_FILE`` when an operator pins a private CA. Host
behaviour stops mattering for the broken-interpreter case while a host that
already trusts a private CA keeps its store (R3-002); a URI that names its own
bundle (``tlsCAFile``, ``tls_ca_file``, ``ssl_ca_certs``) is left alone; and a
non-TLS URI never receives a TLS option (R3-001).

Keeping one construction site also keeps ``connect=False`` in one place: building
the client must not open a socket, and the unroutable test URIs rely on it.
"""

from __future__ import annotations

import os
import ssl
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


def host_trust_store_available() -> bool:
    """True when the interpreter has a usable default CA store (R3-002).

    A deployment whose OS store carries a private CA must keep using it;
    certifi is only a fallback for interpreters that have nothing (a python.org
    build before `Install Certificates.command`, this repo's local case).
    """
    from_env = os.environ.get("SSL_CERT_FILE")
    if from_env and os.path.exists(from_env):
        return True
    paths = ssl.get_default_verify_paths()
    if paths.cafile and os.path.exists(paths.cafile):
        return True
    return bool(paths.capath and os.path.isdir(paths.capath)
                and os.listdir(paths.capath))


def client_kwargs(settings: Settings) -> dict[str, Any]:
    """Keyword arguments for `MongoClient`, TLS trust included.

    Rules, in order (R3-001 and R3-002 are the review findings that shaped
    them):

    1. A non-TLS URI gets no TLS option at all. Measured on pymongo 4.19: such
       an option is accepted and ignored rather than rejected, but injecting it
       would still suggest TLS where there is none.
    2. A URI that names its own bundle keeps it; injecting a second one would at
       best be dead code and at worst shadow the operator's choice.
    3. `MONGODB_TLS_CA_FILE` pins a bundle explicitly.
    4. Otherwise certifi's bundle is used **only** when the interpreter has no
       host store; a host that already trusts a private CA is left alone.
    """
    kwargs: dict[str, Any] = {"connect": False}
    uri = settings.mongodb_uri
    if not uses_tls(uri) or uri_tls_ca_file(uri):
        return kwargs
    if settings.mongodb_tls_ca_file:
        kwargs["tlsCAFile"] = settings.mongodb_tls_ca_file
    elif not host_trust_store_available():
        kwargs["tlsCAFile"] = certifi.where()
    return kwargs


def build_client(settings: Settings) -> MongoClient:
    """Build the lazy client every entry point uses."""
    return MongoClient(settings.mongodb_uri, **client_kwargs(settings))
