"""api.scrapers.browser.build_chrome — the single Chrome factory (D8, K-7).

Every Selenium interaction is faked through monkeypatching: no real browser,
driver or Selenium Manager round-trip ever happens in these tests.
"""

from __future__ import annotations

import subprocess
import sys

import pytest
from selenium import webdriver
from selenium.webdriver.chrome import service as chrome_service_module

from api.config import Settings
from api.scrapers.browser import build_chrome


class FakeOptions:
    """Stand-in for selenium.webdriver.ChromeOptions."""

    def __init__(self) -> None:
        self.arguments: list[str] = []

    def add_argument(self, argument: str) -> None:
        self.arguments.append(argument)


class RecordingService:
    """Stand-in for selenium.webdriver.chrome.service.Service."""

    calls: list[tuple] = []

    def __init__(self, *args) -> None:
        RecordingService.calls.append(args)
        self.args = args


class RecordingChrome:
    """Stand-in for selenium.webdriver.Chrome; never starts a real browser."""

    calls: list[dict] = []
    last_instance: "RecordingChrome | None" = None

    def __init__(self, **kwargs) -> None:
        RecordingChrome.calls.append(kwargs)
        RecordingChrome.last_instance = self


@pytest.fixture(autouse=True)
def fake_selenium(monkeypatch):
    RecordingService.calls.clear()
    RecordingChrome.calls.clear()
    RecordingChrome.last_instance = None
    monkeypatch.setattr(webdriver, "ChromeOptions", FakeOptions)
    monkeypatch.setattr(webdriver, "Chrome", RecordingChrome)
    monkeypatch.setattr(chrome_service_module, "Service", RecordingService)


def test_default_settings_spawn_service_without_a_path():
    # No CHROMEDRIVER_PATH: Selenium Manager must resolve the driver, so the
    # service gets no explicit path.
    driver = build_chrome(Settings())
    assert RecordingService.calls == [()]
    assert set(RecordingChrome.calls[0]) == {"service", "options"}
    assert isinstance(RecordingChrome.calls[0]["service"], RecordingService)
    assert isinstance(RecordingChrome.calls[0]["options"], FakeOptions)
    assert RecordingChrome.last_instance is driver


def driver_options() -> FakeOptions:
    """Options kwarg captured in the most recent Chrome call (helper)."""
    return RecordingChrome.calls[0]["options"]


def test_default_options_are_the_legacy_ones_and_not_headless():
    build_chrome(Settings())
    arguments = driver_options().arguments
    assert "--no-sandbox" in arguments
    assert "--disable-dev-shm-usage" in arguments
    assert not any(arg.startswith("--headless") for arg in arguments)


def test_configured_path_is_passed_to_the_service():
    build_chrome(Settings(chromedriver_path="/usr/local/bin/chromedriver"))
    assert RecordingService.calls == [("/usr/local/bin/chromedriver",)]


def test_headless_opt_in_adds_the_new_headless_flag():
    build_chrome(Settings(chrome_headless=True))
    assert "--headless=new" in driver_options().arguments


def test_extra_arguments_are_appended_in_order_after_headless():
    build_chrome(Settings(chrome_headless=True),
                 extra_arguments=("--lang=es-AR", "--window-size=1280,800"))
    arguments = driver_options().arguments
    assert arguments == [
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--headless=new",
        "--lang=es-AR",
        "--window-size=1280,800",
    ]


def test_importing_the_module_does_not_import_selenium():
    # Fresh interpreter: importing api.scrapers.browser (and its api package
    # parents) must never pull Selenium in — it is imported lazily inside
    # build_chrome so the container can depend on this module for free.
    result = subprocess.run(
        [sys.executable, "-c",
         "import sys, api.scrapers.browser; print('selenium' in sys.modules)"],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False"
