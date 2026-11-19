"""Tests for api.config.Settings — typed, env-driven application settings."""

import dataclasses
import os

import pytest

from api.config import (DEFAULT_MONGO_DB, DEFAULT_MONGO_URI,
                        DEFAULT_SECRET_KEY, ENV_FILE_VARIABLE, Settings,
                        load_env_file)


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


def test_browser_settings_default_to_legacy_behaviour():
    # No path configured: Selenium Manager resolves a matching driver (D8).
    # Headless defaults off: today's scrapers run in a visible window.
    settings = Settings()
    assert settings.chromedriver_path is None
    assert settings.chrome_headless is False


def test_from_env_reads_chromedriver_path():
    settings = Settings.from_env({"CHROMEDRIVER_PATH": "/usr/local/bin/chromedriver"})
    assert settings.chromedriver_path == "/usr/local/bin/chromedriver"


def test_from_env_empty_chromedriver_path_counts_as_unset():
    settings = Settings.from_env({"CHROMEDRIVER_PATH": ""})
    assert settings.chromedriver_path is None


@pytest.mark.parametrize("raw", ["1", "true", "TRUE", "yes", "on", " On "])
def test_from_env_truthy_headless_values(raw):
    assert Settings.from_env({"CHROME_HEADLESS": raw}).chrome_headless is True


@pytest.mark.parametrize("raw", ["0", "false", "no", "", "maybe"])
def test_from_env_falsy_headless_values(raw):
    assert Settings.from_env({"CHROME_HEADLESS": raw}).chrome_headless is False


def test_chrome_binary_defaults_to_none():
    # No CHROME_BINARY: the browser binary is Selenium's business (it looks
    # for a chrome binary in PATH and Selenium Manager can handle it).
    assert Settings().chrome_binary is None
    assert Settings.from_env({}).chrome_binary is None


def test_from_env_reads_chrome_binary():
    settings = Settings.from_env({"CHROME_BINARY": "/usr/bin/chromium"})
    assert settings.chrome_binary == "/usr/bin/chromium"


def test_tls_ca_file_defaults_to_none():
    # Unset means "use certifi's bundle for TLS URIs" (api/mongo.py, D-17).
    assert Settings().mongodb_tls_ca_file is None
    assert Settings.from_env({}).mongodb_tls_ca_file is None


def test_from_env_reads_tls_ca_file():
    settings = Settings.from_env({"MONGODB_TLS_CA_FILE": "/private/etc/ca.pem"})
    assert settings.mongodb_tls_ca_file == "/private/etc/ca.pem"


def test_from_env_empty_tls_ca_file_counts_as_unset():
    assert Settings.from_env({"MONGODB_TLS_CA_FILE": ""}).mongodb_tls_ca_file is None


def test_from_env_empty_chrome_binary_counts_as_unset():
    settings = Settings.from_env({"CHROME_BINARY": ""})
    assert settings.chrome_binary is None


def test_settings_is_frozen():
    settings = Settings()
    try:
        settings.secret_key = "rotated"
    except dataclasses.FrozenInstanceError:
        pass
    else:
        raise AssertionError("Settings must be frozen")


# -- load_env_file: the explicit environment-file selector -------------------------

def _write_env_file(tmp_path, name=".env", **variables):
    path = tmp_path / name
    path.write_text("\n".join(
        f"{key}={value}" for key, value in variables.items()))
    return str(path)


def test_load_env_file_honours_the_selector_variable(monkeypatch, tmp_path):
    path = _write_env_file(tmp_path, MONGODB_DB="selector_db")
    monkeypatch.setenv(ENV_FILE_VARIABLE, path)
    monkeypatch.delenv("MONGODB_DB", raising=False)

    assert load_env_file(".env") == path
    assert os.environ["MONGODB_DB"] == "selector_db"
    # dotenv wrote it behind monkeypatch's back: re-register so teardown
    # restores the environment and nothing leaks into the next test.
    monkeypatch.setenv("MONGODB_DB", os.environ["MONGODB_DB"])


def test_load_env_file_falls_back_to_the_default_argument(monkeypatch, tmp_path):
    path = _write_env_file(tmp_path, MONGODB_DB="default_db")
    monkeypatch.delenv(ENV_FILE_VARIABLE, raising=False)
    monkeypatch.delenv("MONGODB_DB", raising=False)

    assert load_env_file(path) == path
    assert os.environ["MONGODB_DB"] == "default_db"
    monkeypatch.setenv("MONGODB_DB", os.environ["MONGODB_DB"])


def test_load_env_file_without_path_loads_nothing_and_returns_none(monkeypatch):
    monkeypatch.delenv(ENV_FILE_VARIABLE, raising=False)
    monkeypatch.delenv("MONGODB_DB", raising=False)

    assert load_env_file() is None
    # -- exactly the environment it came in with: nothing was loaded
    assert "MONGODB_DB" not in os.environ


def test_load_env_file_never_overrides_an_exported_variable(monkeypatch, tmp_path):
    path = _write_env_file(tmp_path, MONGODB_DB="file_db")
    monkeypatch.setenv(ENV_FILE_VARIABLE, path)
    monkeypatch.setenv("MONGODB_DB", "already_exported")

    assert load_env_file() == path
    assert os.environ["MONGODB_DB"] == "already_exported"
    monkeypatch.setenv("MONGODB_DB", os.environ["MONGODB_DB"])


def test_load_env_file_selector_naming_a_missing_file_raises(
        monkeypatch, tmp_path):
    """An explicitly selected file that is not there must not fall back to
    the shell defaults: that is how a typo runs a scraper against the wrong
    database (R3-ENV-SELECTOR-FAIL-OPEN)."""
    missing = str(tmp_path / "does-not-exist")
    monkeypatch.setenv(ENV_FILE_VARIABLE, missing)
    monkeypatch.delenv("MONGODB_DB", raising=False)
    monkeypatch.delenv("MONGODB_URI", raising=False)

    with pytest.raises(FileNotFoundError) as excinfo:
        load_env_file()

    assert ENV_FILE_VARIABLE in str(excinfo.value)
    assert "MONGODB_DB" not in os.environ
    assert "MONGODB_URI" not in os.environ


def test_load_env_file_default_that_is_missing_is_not_an_error(
        monkeypatch, tmp_path):
    """A *default* file may legitimately be absent (fresh clone, CI): the
    selector is unset, so nothing was promised and nothing may fail."""
    missing = str(tmp_path / "absent.env")
    monkeypatch.delenv(ENV_FILE_VARIABLE, raising=False)
    monkeypatch.delenv("MONGODB_DB", raising=False)

    assert load_env_file(missing) is None
    assert "MONGODB_DB" not in os.environ
