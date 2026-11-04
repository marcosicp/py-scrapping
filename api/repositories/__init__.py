"""Repositories: persistence ports and adapters (T2).

Port-level errors live here, on the port surface, not in the module that
holds the infrastructurespecific mongo adapter.
"""

from __future__ import annotations


class RepositoryUnavailable(Exception):
    """The persistence layer could not be reached.

    Translated shape of a driver failure (``PyMongoError``) raised by the
    mongo adapter so the HTTP layer never sees pymongo types and fakes can
    raise the same type in tests.
    """
