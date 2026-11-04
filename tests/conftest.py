"""Shared pytest fixtures for the LaListita test suite."""

import pytest

from api.config import Settings
from app import create_app


@pytest.fixture
def settings():
    # MONGODB_URI points at an unroutable address on purpose: any accidental
    # database access during a test fails fast and can never reach a real
    # database.
    return Settings(
        secret_key="test-secret",
        mongodb_uri="mongodb://127.0.0.1:1/?serverSelectionTimeoutMS=200",
        mongodb_db="lalistita_test",
    )


@pytest.fixture
def app(settings):
    application = create_app(settings)
    application.config["TESTING"] = True
    return application


@pytest.fixture
def client(app):
    return app.test_client()
