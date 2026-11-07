# Bugfix — MongoDB TLS fails locally: the interpreter has no CA trust store

Reported 2026-11-07 by the owner: running the project locally, every Atlas
connection dies with

```
pymongo.errors.ServerSelectionTimeoutError: ac-gvkcjqj-shard-00-0X.fosxvtw.mongodb.net:27017:
[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer
certificate (_ssl.c:1147) ... topology_type: ReplicaSetNoPrimary
```

Branch: `fix/mongodb-tls-ca-file` (base `main` `c766ac9`).

## 1. Root cause (measured, not inferred)

The Python 3.15 installed from python.org on this Mac has an **empty OpenSSL
trust store**:

```
python            : 3.15.2  (.venv/bin/python)
OpenSSL           : OpenSSL 3.5.9
ssl default cafile: None
openssl_cafile    : /Library/Frameworks/Python.framework/Versions/3.15/etc/openssl/cert.pem
¿existe?          : False
listado del dir   : []                        ← vacío
/Applications/Python 3.15/Install Certificates.command   ← nunca se ejecutó
```

`Install Certificates.command` is what symlinks `certifi/cacert.pem` into that
directory. Without it the interpreter trusts **zero** certificate authorities,
so the TLS handshake with Atlas cannot validate the server chain and OpenSSL
answers `unable to get local issuer certificate` — once per shard, which is why
the message repeats three times.

Proof against the real cluster, from the project venv:

| wiring | result |
| --- | --- |
| `MongoClient(uri)` — what `app.py` did | **FAIL** `[SSL: CERTIFICATE_VERIFY_FAILED]` |
| `MongoClient(uri, tlsCAFile=certifi.where())` | **OK** (`admin.command("ping")`) |

So credentials, network, SRV resolution and the URI are fine; only the CA bundle
was missing.

### Why only Mongo broke, not the scrapers

`requests` does not use the interpreter store — it ships `certifi` and applies
that bundle itself. That is why `requests==2.34.2` + `certifi==2026.10.23` were
already pinned and HTTP scraping worked while Mongo did not: pymongo delegates
TLS to the `ssl` module defaults. Render/Docker also worked because the Debian
image ships `ca-certificates`. The defect is host-dependent, so the fix must not
depend on the host.

## 2. Decision

- **D-17 — the client owns its trust store.** `MongoClient` is built with
  `tlsCAFile=certifi.where()` for any TLS URI (`mongodb+srv://`, or `tls=true` /
  `ssl=true` in the query string). `certifi` is already a pinned runtime
  dependency, so this adds no dependency and makes local, Docker and Render
  behave identically. A plain `mongodb://localhost:27017/` keeps its old wiring
  byte for byte: no TLS option is injected when TLS is not requested.
- **D-18 — operator override.** New setting `MONGODB_TLS_CA_FILE`
  (`Settings.mongodb_tls_ca_file`) replaces certifi's bundle when the operator
  needs a private CA; when set it applies to every URI, because it is an
  explicit decision, not a default.
- **D-19 — one construction site.** Both entry points (`app.py::_init_mongo`,
  `api/cli.py::build_manager`) go through `api/mongo.py::build_client`, so the
  trust-store rule cannot drift between Flask and the CLI. `client_kwargs()` is
  a pure function, which is what the tests assert; no pymongo internals are
  inspected.
- `connect=False` stays: building the app must not open a socket, and the
  unroutable test URIs depend on it.

## 3. Tasks

- [x] T1 — `tests/test_mongo.py` + a `test_config.py` case for the new setting,
      RED before the implementation.
- [x] T2 — `api/mongo.py` (`uses_tls`, `client_kwargs`, `build_client`).
- [x] T3 — `api/config.py` setting `MONGODB_TLS_CA_FILE`.
- [x] T4 — wire `app.py` and `api/cli.py`; adapt `tests/test_cli.py`'s fake to
      the new seam (`cli.build_client`).
- [x] T5 — verification, docs sync and native review.

## 4. Verification

| Check | Result |
| --- | --- |
| `pytest tests/test_mongo.py` before the implementation | **RED** `ModuleNotFoundError: No module named 'api.mongo'` |
| `pytest` | **423 passed, 9 skipped** in 2.97 s (was 405: +15 `uses_tls`/`client_kwargs` cases, +3 `Settings` cases) |
| flake8 CI gate | 0 |
| **end-to-end against the real cluster** | `create_app()` + `GET /api/productos/agrupados` → **200**, **15 311** rows, counts `carre 6187 / disco 4720 / hiper 3036 / mami 3251`, 2.6 s — the exact path that raised `ServerSelectionTimeoutError` before |

The end-to-end row is the point: it exercises Flask's own wiring, not a probe
script, against `cluster0.fosxvtw.mongodb.net`.

## 5. Follow-ups

- The owner may still want `Install Certificates.command` for the *rest* of that
  interpreter's TLS (curl-like tools inside Python); the application no longer
  depends on it.
