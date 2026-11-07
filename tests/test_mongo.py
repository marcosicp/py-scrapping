"""MongoClient construction: the TLS trust store the client owns (D-17/D-19).

These tests never touch the network: they assert the *decision* (`uses_tls`,
`client_kwargs`) and that `build_client` keeps `connect=False`, which is what
keeps an unroutable URI inert.

Why this matters: a python.org interpreter on macOS ships an empty OpenSSL
certificate directory (`.../etc/openssl/cert.pem` does not exist) until
`Install Certificates.command` runs, so any TLS handshake fails with
`certificate verify failed: unable to get local issuer certificate`. pymongo
uses those defaults while `requests` carries its own `certifi` bundle — the
asymmetry that made Atlas fail locally while scraping worked.
"""

import certifi
import pytest
from pymongo import MongoClient

from api.config import Settings
from api.mongo import build_client, client_kwargs, uses_tls


@pytest.mark.parametrize("uri", [
    "mongodb+srv://user:pw@cluster0.example.net/db",
    "mongodb+srv://user:pw@cluster0.example.net/db?retryWrites=true&w=majority",
    "mongodb://host1:27017,host2:27017/db?tls=true",
    "mongodb://host:27017/db?ssl=true",
    "mongodb://host:27017/db?tls=1",
    "mongodb://host:27017/db?TLS=True",
])
def test_uses_tls_for_srv_and_explicit_flags(uri):
    assert uses_tls(uri) is True


@pytest.mark.parametrize("uri", [
    "mongodb://localhost:27017/",
    "mongodb://host:27017/db",
    "mongodb://host:27017/db?tls=false",
    "mongodb://host:27017/db?ssl=false",
])
def test_uses_tls_is_false_without_a_tls_request(uri):
    assert uses_tls(uri) is False


def test_client_kwargs_inject_certifi_for_a_tls_uri():
    kwargs = client_kwargs(Settings(mongodb_uri="mongodb+srv://u:p@host/db"))
    assert kwargs == {"connect": False, "tlsCAFile": certifi.where()}


def test_client_kwargs_leave_a_plain_uri_untouched():
    kwargs = client_kwargs(Settings(mongodb_uri="mongodb://localhost:27017/"))
    assert kwargs == {"connect": False}


def test_explicit_ca_file_overrides_certifi():
    settings = Settings(
        mongodb_uri="mongodb+srv://u:p@host/db",
        mongodb_tls_ca_file="/private/etc/private-ca.pem",
    )
    assert client_kwargs(settings)["tlsCAFile"] == "/private/etc/private-ca.pem"


def test_explicit_ca_file_applies_even_without_a_tls_uri():
    # -- an operator who names a bundle made a decision; honour it as-is
    settings = Settings(
        mongodb_uri="mongodb://localhost:27017/",
        mongodb_tls_ca_file="/private/etc/private-ca.pem",
    )
    assert client_kwargs(settings)["tlsCAFile"] == "/private/etc/private-ca.pem"


def test_build_client_returns_a_lazy_client():
    # -- the unroutable host proves nothing connects at build time
    client = build_client(Settings(mongodb_uri="mongodb+srv://u:p@host.invalid/db"))
    assert isinstance(client, MongoClient)
