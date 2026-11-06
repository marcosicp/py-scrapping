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

An environment variable set to the empty string counts as unset — that is how
blank entries in `.env` behave for these defaults.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

DEFAULT_SECRET_KEY = "secret!"
DEFAULT_MONGO_URI = "mongodb://localhost:27017/"
DEFAULT_MONGO_DB = "lalistitadev"

# The environment variable may be present but empty; treat that as unset
# (`env.get(NAME) or DEFAULT`).
_SECRET_KEY_ENV = "SECRET_KEY"
_MONGO_URI_ENV = "MONGODB_URI"
_MONGO_DB_ENV = "MONGODB_DB"
_CHROMEDRIVER_PATH_ENV = "CHROMEDRIVER_PATH"
_CHROME_HEADLESS_ENV = "CHROME_HEADLESS"
_CHROME_BINARY_ENV = "CHROME_BINARY"

# Truthy spellings accepted for CHROME_HEADLESS (case-insensitive, stripped).
_HEADLESS_TRUE = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """Immutable application settings, resolved from the environment."""

    secret_key: str = DEFAULT_SECRET_KEY
    mongodb_uri: str = DEFAULT_MONGO_URI
    mongodb_db: str = DEFAULT_MONGO_DB
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
            chromedriver_path=source.get(_CHROMEDRIVER_PATH_ENV) or None,
            chrome_headless=(source.get(_CHROME_HEADLESS_ENV) or "")
            .strip().lower() in _HEADLESS_TRUE,
            chrome_binary=source.get(_CHROME_BINARY_ENV) or None,
        )
