"""Typed application settings.

`Settings.from_env()` is the single place where environment variables become
application configuration. `create_app(settings=...)` consumes the resulting
frozen dataclass, which keeps the composition root dependency-injectable and
lets tests pass explicit settings instead of mutating `os.environ`.

Defaults are the legacy values the app used before this module existed:

- `SECRET_KEY` stays the legacy `"secret!"`. Rotating it is known-issue K-13 and
  is out of scope here.
- `MONGODB_URI` / `MONGODB_DB` keep the dev-database defaults.

The Chrome factory (D8) adds two more settings so the driver does not have to
be hardcoded in the scrapers (K-7):

- `CHROMEDRIVER_PATH` — optional absolute path to a chromedriver binary.
  Unset by default: Selenium Manager then resolves a driver matching the
  installed Chrome.
- `CHROME_HEADLESS` — opt-in headless mode. The default is off, preserving
  the visible browser window the legacy scrapers showed.
- `CHROME_BINARY` — optional absolute path to the browser binary itself (for
  example Debian's `/usr/bin/chromium`). Unset by default: the binary is then
  guessed heuristically (Selenium Manager probes candidate paths and
  chromedriver falls back to well-known names), and when that guess does not
  match the host the session fails with `session not created` /
  binary-not-found. Setting this variable pins `binary_location` and removes
  the guess.
- `MONGODB_TLS_CA_FILE` — optional absolute path to the CA bundle used to
  verify a TLS MongoDB connection. Unset by default: TLS URIs then use
  certifi's bundle (`api/mongo.py`, D-17), which is what makes a python.org
  interpreter with an empty OpenSSL store work against Atlas.

An environment variable set to the empty string counts as unset — that is how
blank entries in `.env` behave for these defaults.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

import dotenv

DEFAULT_SECRET_KEY = "secret!"
DEFAULT_MONGO_URI = "mongodb://localhost:27017/"
DEFAULT_MONGO_DB = "lalistitadev"

# Selects the env file both entry points load, e.g.
# LALISTITA_ENV_FILE=.env.local python app.py.
ENV_FILE_VARIABLE = "LALISTITA_ENV_FILE"

# The environment variable may be present but empty; treat that as unset
# (`env.get(NAME) or DEFAULT`).
_SECRET_KEY_ENV = "SECRET_KEY"
_MONGO_URI_ENV = "MONGODB_URI"
_MONGO_DB_ENV = "MONGODB_DB"
_MONGO_TLS_CA_FILE_ENV = "MONGODB_TLS_CA_FILE"
_CHROMEDRIVER_PATH_ENV = "CHROMEDRIVER_PATH"
_CHROME_HEADLESS_ENV = "CHROME_HEADLESS"
_CHROME_BINARY_ENV = "CHROME_BINARY"

# Truthy spellings accepted for CHROME_HEADLESS (case-insensitive, stripped).
_HEADLESS_TRUE = {"1", "true", "yes", "on"}


# The repository root: `api/config.py` lives one level below it, next to
# `app.py`. A relative env path resolves here so the entry points never depend
# on where the operator happened to be standing.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _resolve_env_path(path: str) -> str:
    """An absolute env path; a relative one is anchored at the project root."""
    return path if os.path.isabs(path) else os.path.join(_PROJECT_ROOT, path)


def load_env_file(default: str | None = None) -> str | None:
    """Load the env file the selector names, or `default` when it is unset.

    Exists so the two entry points (Flask and `api.cli`) can read the same
    explicitly chosen file instead of silently retargeting each other at a
    different database: `LALISTITA_ENV_FILE=.env.local` makes both `python
    app.py` and `python -m api.cli` work against the local mongod.

    - No path at all (selector unset and no default): load nothing and
      return `None` — the caller keeps exactly the environment it had.
    - Otherwise load the file with `override=False`, so a variable already
      exported in the shell always wins over the file, and return the path
      that was actually loaded.
    - A **relative** path resolves against the project root (the directory
      that holds `app.py`), never against the caller's working directory.
      That is the behaviour the bare `load_dotenv()` had — it searched
      upward from the caller's file — and it is what keeps
      `python /path/to/repo/app.py` reading the repo's `.env` from any
      directory instead of silently falling back to the default database
      (R3-ENV-SEARCH-REGRESSION).
    - An explicitly selected file that does not exist raises
      `FileNotFoundError`: the operator named that file, so falling back to
      the shell defaults would silently start the app or a scraper against a
      different database — the exact failure this helper exists to prevent.
      A *default* file that does not exist is not an error (`.env` is absent
      in a fresh clone and in CI); it loads nothing and returns `None`.
    """
    explicit = os.environ.get(ENV_FILE_VARIABLE)
    path = explicit or default
    if not path:
        return None
    resolved = _resolve_env_path(path)
    if not os.path.isfile(resolved):
        if explicit:
            raise FileNotFoundError(
                f"{ENV_FILE_VARIABLE}={explicit!r} names a file that does "
                f"not exist")
        return None
    dotenv.load_dotenv(resolved, override=False)
    return resolved


@dataclass(frozen=True)
class Settings:
    """Immutable application settings, resolved from the environment."""

    secret_key: str = DEFAULT_SECRET_KEY
    mongodb_uri: str = DEFAULT_MONGO_URI
    mongodb_db: str = DEFAULT_MONGO_DB
    mongodb_tls_ca_file: str | None = None
    chromedriver_path: str | None = None
    chrome_headless: bool = False
    chrome_binary: str | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        """Build settings from `env`, defaulting to `os.environ`.

        Empty-string values count as unset and fall back to the defaults.
        """
        source = os.environ if env is None else env
        return cls(
            secret_key=source.get(_SECRET_KEY_ENV) or DEFAULT_SECRET_KEY,
            mongodb_uri=source.get(_MONGO_URI_ENV) or DEFAULT_MONGO_URI,
            mongodb_db=source.get(_MONGO_DB_ENV) or DEFAULT_MONGO_DB,
            mongodb_tls_ca_file=source.get(_MONGO_TLS_CA_FILE_ENV) or None,
            chromedriver_path=source.get(_CHROMEDRIVER_PATH_ENV) or None,
            chrome_headless=(source.get(_CHROME_HEADLESS_ENV) or "")
            .strip().lower() in _HEADLESS_TRUE,
            chrome_binary=source.get(_CHROME_BINARY_ENV) or None,
        )
