"""Tests for api.config.Settings — typed, env-driven application settings."""

import dataclasses

from api.config import DEFAULT_MONGO_DB, DEFAULT_MONGO_URI, DEFAULT_SECRET_KEY, Settings


def test_defaults_are_the_legacy_values():
    settings = Settings()
    assert settings.secret_key == "secret!"
    assert settings.mongodb_uri == "mongodb://localhost:27017/"
    assert settings.mongodb_db == "lalistitadev"


def test_module_constants_match_the_defaults():
    assert DEFAULT_SECRET_KEY == "secret!"
    assert DEFAULT_MONGO_URI == "mongodb://localhost:27017/"
    assert DEFAULT_MONGO_DB == "lalistitadev"


def test_from_env_with_empty_mapping_equals_defaults():
    assert Settings.from_env({}) == Settings()


def test_from_env_reads_all_three_variables():
    env = {
        "SECRET_KEY": "s3cret",
        "MONGODB_URI": "mongodb://example.net:27017/",
        "MONGODB_DB": "other_db",
    }
    settings = Settings.from_env(env)
    assert settings.secret_key == "s3cret"
    assert settings.mongodb_uri == "mongodb://example.net:27017/"
    assert settings.mongodb_db == "other_db"


def test_from_env_empty_string_counts_as_unset():
    env = {"SECRET_KEY": "", "MONGODB_URI": "", "MONGODB_DB": ""}
    assert Settings.from_env(env) == Settings()


def test_from_env_partial_override_keeps_defaults_for_the_rest():
    env = {"MONGODB_URI": "mongodb://example.net:27017/"}
    settings = Settings.from_env(env)
    assert settings.mongodb_uri == "mongodb://example.net:27017/"
    assert settings.secret_key == "secret!"
    assert settings.mongodb_db == "lalistitadev"


def test_settings_is_frozen():
    settings = Settings()
    try:
        settings.secret_key = "rotated"
    except dataclasses.FrozenInstanceError:
        pass
    else:
        raise AssertionError("Settings must be frozen")
