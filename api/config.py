"""Typed application settings.

`Settings.from_env()` is the single place where environment variables become
application configuration. `create_app(settings=...)` consumes the resulting
frozen dataclass, which keeps the composition root dependency-injectable and
lets tests pass explicit settings instead of mutating `os.environ`.

Defaults are the legacy values the app used before this module existed:

- `SECRET_KEY` stays the legacy `"secret!"`. Rotating it is known-issue K-13 and
  is out of scope here.
- `MONGODB_URI` / `MONGODB_DB` keep the dev-database defaults.

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


@dataclass(frozen=True)
class Settings:
    """Immutable application settings, resolved from the environment."""

    secret_key: str = DEFAULT_SECRET_KEY
    mongodb_uri: str = DEFAULT_MONGO_URI
    mongodb_db: str = DEFAULT_MONGO_DB

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
        )
