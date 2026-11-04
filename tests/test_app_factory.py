"""Tests for app.create_app — settings-driven composition of the Flask app.

The fixtures live in tests/conftest.py: `settings` points MONGODB_URI at an
unroutable address on purpose, so the factory can never reach a real database.
"""

from flask import Flask

from api.config import Settings
from app import create_app

REQUIRED_RULES = [
    "/",
    "/scrape",
    "/supermercados",
    "/scraping-disco",
    "/scraping-carrefour",
    "/scraping-changomas",
    "/scraping-hiperlibertad",
    "/scraping-supermami",
]


def test_create_app_returns_a_flask_app_with_settings_applied(app):
    assert isinstance(app, Flask)
    assert app.config["SECRET_KEY"] == "test-secret"


def test_create_app_attaches_both_legacy_mongo_handles(app, settings):
    assert app.mongodb_client is not None
    assert app.database.name == settings.mongodb_db
    assert app.database.client is app.mongodb_client


def test_create_app_reads_the_environment_when_no_settings_are_passed(monkeypatch):
    # Clear SECRET_KEY so a developer's local .env (loaded at import by app.py)
    # cannot change the expected default.
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("MONGODB_DB", "env_chosen_db")
    app = create_app()
    assert app.database.name == "env_chosen_db"
    assert app.config["SECRET_KEY"] == Settings.from_env(dict()).secret_key


def test_create_app_does_not_open_a_connection(settings):
    # The unroutable URI would hang or raise on first I/O; building the app
    # must stay instant because MongoClient connects lazily.
    app = create_app(settings)
    assert app.mongodb_client is not None


def test_url_map_keeps_the_legacy_rules(app):
    rules = {rule.rule for rule in app.url_map.iter_rules()}
    for required in REQUIRED_RULES:
        assert required in rules, f"missing rule: {required}"


def test_socketio_is_initialised(app):
    assert "socketio" in app.extensions


def test_get_scrape_page_returns_200(client):
    response = client.get("/scrape")
    assert response.status_code == 200
