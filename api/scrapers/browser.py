"""Chrome driver factory (D8, K-7).

The legacy scrapers each hardcode their own driver construction with a pinned
``chromedriver-141`` bin-path (K-7), which stops matching the installed Chrome
on every browser update. This module is the single place a Chrome driver is
built, driven by two environment settings on ``Settings``:

- ``CHROMEDRIVER_PATH`` — when set, that binary is passed to ``Service``;
  when unset (the default), ``Service()`` has no path and Selenium Manager
  resolves a driver matching the installed Chrome (needs network on first
  use).
- ``CHROME_HEADLESS`` — opt-in headless mode; the default stays OFF to
  preserve today's visible-window behaviour.

Selenium is imported inside ``build_chrome`` — never at module level — so
importing this module (for instance from ``api.container``) does not pull
Selenium in.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from api.config import Settings

if TYPE_CHECKING:
    from selenium.webdriver.remote.webdriver import WebDriver


def build_chrome(settings: Settings, *,
                 extra_arguments: Sequence[str] = ()) -> "WebDriver":
    """Build a Chrome ``WebDriver`` from ``settings``.

    ``--no-sandbox`` and ``--disable-dev-shm-usage`` are always added (the
    legacy options), then ``--headless=new`` when ``settings.chrome_headless``
    is on, then every ``extra_arguments`` entry in order. The service uses
    ``settings.chromedriver_path`` when configured, otherwise Selenium
    Manager.
    """
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service

    options = webdriver.ChromeOptions()
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    if settings.chrome_headless:
        options.add_argument('--headless=new')
    for argument in extra_arguments:
        options.add_argument(argument)

    if settings.chromedriver_path:
        service = Service(settings.chromedriver_path)
    else:
        service = Service()

    return webdriver.Chrome(service=service, options=options)
