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
from api.mongo import build_client, client_kwargs, uri_tls_ca_file, uses_tls


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


@pytest.mark.parametrize("uri", [
    "mongodb+srv://u:p@host/db?tlsCAFile=/private/private-ca.pem",
    "mongodb+srv://u:p@host/db?tls_ca_file=/private/private-ca.pem",
    "mongodb://host:27017/db?ssl_ca_certs=/private/private-ca.pem",
    "mongodb+srv://u:p@host/db?TLSCAFILE=/private/private-ca.pem",
])
def test_uri_tls_ca_file_reads_every_alias(uri):
    assert uri_tls_ca_file(uri) == "/private/private-ca.pem"


def test_uri_tls_ca_file_is_none_without_a_bundle():
    assert uri_tls_ca_file("mongodb+srv://u:p@host/db") is None
    assert uri_tls_ca_file("mongodb://localhost:27017/") is None


@pytest.mark.parametrize("uri", [
    "mongodb+srv://u:p@host/db?tlsCAFile=/private/private-ca.pem",
    "mongodb://host:27017/db?ssl_ca_certs=/private/private-ca.pem",
])
def test_a_uri_ca_file_is_never_overridden(uri):
    # -- R3-001: pymongo reads the URI's bundle, so injecting certifi there is
    # dead code at best and shadowing the operator's choice at worst
    assert client_kwargs(Settings(mongodb_uri=uri)) == {"connect": False}


def test_a_uri_ca_file_beats_the_environment_setting():
    settings = Settings(
        mongodb_uri="mongodb+srv://u:p@host/db?tlsCAFile=/private/private-ca.pem",
        mongodb_tls_ca_file="/private/etc/other-ca.pem",
    )
    assert client_kwargs(settings) == {"connect": False}
