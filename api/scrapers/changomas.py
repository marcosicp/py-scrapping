"""ChangoMas scraper, ported to the scraper contract (T11) — the K-12 fix.

Mechanical port of ``api.scrapers.scrap_changomas`` (the byte-identical legacy
reference, deleted in T14): the discovery visit, the section discovery from
the ``categoryList-container__items`` / ``categoryItem`` anchors, the section
URL prefix, the scroll, the ``vtex-search-result-3-x-totalProducts--layout``
total read (which the legacy never uses), the ``gallery-layout-container``
result read, the empty-results abort, the 2-page-capped page loop, the
json-LD extraction over the re-fetched discovery page, the substring dedupe
guard, the per-section name sort and every print are kept verbatim.

**The K-12 fix:** the legacy ended each section with
``open('.changomas/almacen/<file>.json', 'w')`` + ``json.dump`` — a silent
data black hole: ``.changomas/`` is gitignored and nothing ever reaches
MongoDB or the API. The port persists through the repository instead
(``ctx.save`` → ``ProductRepository.replace_products``) and clears the
accumulated list right after saving, exactly like the legacy cleared after
writing. ``/supermercados`` still ignores the ``ChangoMas`` group until the
dashboard gains one — that API half of K-12 stays a separate follow-up.

Documented decisions (each commented and tested in
``tests/test_scraper_changomas.py``):

1. The ``if results.__len__() == 0: return`` abort ends the WHOLE run, kept
   verbatim: no further sections, no save, no final report.
2. The legacy page loop re-fetches the DISCOVERY page (not the section page)
   before parsing the json-LD — a quirk kept verbatim; fixing it would
   silently change the collected data.
3. The never-executed ``arender(sleep=8)`` call is deleted, not replaced: it
   was never awaited, so it never ran (K-18).
4. Unexpected errors propagate instead of being swallowed. The legacy outer
   ``except Exception`` printed and returned, so a broken run looked
   successful. The ported run lets them escape — the scraper manager marks
   the run ``failed`` (the same decision 2 the other ports took). The legacy
   per-page ``try/except`` (print, continue) is kept.

Plumbing: the legacy ``async def`` had no ``await`` inside, so it becomes a
plain sync ``run(ctx)``; ``notifyStatus`` became ``ctx.report``,
``_hTMLSession.get`` became ``ctx.http.get``, ``time.sleep`` became
``ctx.sleep``, ``self.activeChangomas`` became ``ctx.should_stop()`` and the
driver comes from ``ctx.browser()``, so the legacy ``driver.close()`` in the
``finally`` disappeared. ``label`` is the accent-free ``"ChangoMas"`` — the
same ASCII-safe value the legacy stored under ``supermercado``, matching the
other ports.
"""

from __future__ import annotations

import json

from bs4 import BeautifulSoup

from api.scrapers.base import BaseScraper, ScrapeContext

DISCOVERY_URL = "https://www.masonline.com.ar/3454?map=productClusterIds"

# The legacy section URL prefix: the visited URL is prefix + <section href
# after ".ar/">, so the section slug rides in the VTEX ``query`` parameter.
SECTION_URL_PREFIX = (
    "https://www.masonline.com.ar/268?initialMap=productClusterIds"
    "&initialQuery=268&map=category-1,productclusternames"
    "&query=/desayuno-y-golosinas/mas-online---almacen")

SCROLL_SCRIPT = "window.scrollTo(0, document.body.scrollHeight/2);"


def _selenium_waits():
    """Import Selenium lazily so the module imports without it (tests swap
    this helper out for fakes; the driver itself arrives from ctx.browser())."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait
    return WebDriverWait, EC, By


class ScraperChangoMas(BaseScraper):
    """Scrapes ChangoMas's almacen sections through a Chrome driver + json-LD.

    ``categories`` is empty: the legacy route's ``categoria`` parameter was
    never used, so any category value is accepted and ignored (the same
    treatment SuperMami got).
    """

    slug = "changomas"
    label = "ChangoMas"
    categories = ()

    def run(self, ctx: ScrapeContext) -> None:
        # A stop requested before the run touches the network keeps it inert
        # (the shared pre-cancelled contract guard; the legacy built the
        # driver first and only stopped inside the page loop).
        if ctx.should_stop():
            return
        # No legacy outer try/except here (decision 4): unexpected errors
        # propagate so the manager marks the run failed instead of letting
        # a broken run look successful.
        WebDriverWait, EC, By = _selenium_waits()
        jsondata = []
        secciones_ = []
        with ctx.browser() as driver:
            driver.maximize_window()
            driver.implicitly_wait(50)
            ctx.report("Inicio scrap")

            driver.get(DISCOVERY_URL)
            ctx.sleep(5)
            seccionesReq = WebDriverWait(driver, 15).until(
                EC.visibility_of_all_elements_located(
                    (By.CLASS_NAME, "categoryList-container__items")))

            secciones = seccionesReq[0].find_elements(
                By.CLASS_NAME, "categoryItem")

            for seccion in secciones:
                href_ = seccion.get_attribute('href').split(".ar/")[1]
                secciones_.append(href_)

            print("secciones " + str(secciones.__len__()))

            for seccion in secciones_:
                # SCRAP DE SECCION
                driver.get(SECTION_URL_PREFIX + seccion)
                driver.execute_script(SCROLL_SCRIPT)
                ctx.sleep(5)

                # LEO EL TOTAL DE LA SECCION (the legacy reads it and never
                # uses it — quirk kept verbatim).
                total = int(driver.find_element(
                    By.CLASS_NAME,
                    "vtex-search-result-3-x-totalProducts--layout"
                ).text.split(" ")[0])

                todos = WebDriverWait(driver, 15).until(
                    EC.visibility_of_all_elements_located(
                        (By.ID, "gallery-layout-container")))
                results = todos[0].find_elements(By.XPATH, "*")

                # Legacy abort kept verbatim: an empty first result read ends
                # the WHOLE run — no further sections, no save, no report.
                if (results.__len__() == 0):
                    return

                for i in range(2, 3):
                    if ctx.should_stop():
                        break

                    try:
                        print('scraping data from ChangoMas - ' +
                              seccion + ' pagina: ' + str(i))
                        # Legacy quirk kept verbatim (decision 2): the page
                        # loop re-fetches the DISCOVERY page, not the section
                        # page, before parsing the json-LD.
                        url = DISCOVERY_URL  # -- set url
                        response = ctx.http.get(url)
                        # -- get data and parse
                        soup = BeautifulSoup(response.text, 'html.parser')

                        anchors = soup.find_all(
                            'div', class_='flex flex-column min-vh-100 w-100')
                        if (len(anchors) > 0):
                            if (anchors[0].next.name != 'script'):
                                flag = False
                                break
                            # for a in anchors:
                            item = anchors[0].next.contents[0]
                            jsonitem = json.loads(item)

                            for jsonitemi in jsonitem["itemListElement"]:
                                try:
                                    if ("name" in jsonitemi["item"]):
                                        jsonitea = {
                                            "supermercado": "ChangoMas",
                                            "name":
                                                jsonitemi["item"]["name"],
                                            "price":
                                                jsonitemi["item"]["offers"][
                                                    "lowPrice"]}
                                        if not any(
                                                element['name'] in
                                                jsonitea['name']
                                                for element in jsondata):
                                            print('Chirp')
                                            jsondata.append(jsonitea)
                                        attempt = 0
                                except Exception:
                                    print("Oops!  That was no valid number."
                                          "  Try again...")
                                    continue
                        else:
                            continue

                    except Exception:
                        continue

                # The K-12 fix: the legacy dumped
                # ``.changomas/almacen/<fileName>.json`` here and cleared the
                # list after writing; the port persists through the
                # repository (clearing after saving is the faithful
                # equivalent) and nothing touches the filesystem.
                jsondata.sort(key=lambda x: x["name"])
                fileName = seccion.split("/")[1]
                ctx.save(jsondata, categoria="almacen",
                         subcategoria=fileName)
                jsondata.clear()

            ctx.report("PROCESO TERMINADO CON " +
                       str(jsondata.__len__()) + " productos")

            print("Proceso changomas termino OK, con " +
                  str(jsondata.__len__()) + " productos")
