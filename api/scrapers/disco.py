"""Disco scraper, ported to the scraper contract (T9).

Mechanical port of ``api.scrapers.scrap_disco`` (the byte-identical legacy
reference, deleted in T14): the hardcoded 14-subcategory list, the VTEX
``?page=`` paging, the json-LD extraction, ``name_parse`` and the stored
keys are unchanged. Only the plumbing moved to the contract:
``notifyStatus`` became ``ctx.report``, ``_hTMLSession.get`` became
``ctx.http.get``, ``time.sleep`` became ``ctx.sleep``, the
``activeDisco`` flag became ``ctx.should_stop()``, ``save_to_mongodb``
became ``ctx.save`` (saving one subcategory at a time, like the legacy
per-subcategory call) and the driver comes from ``ctx.browser()``, so the
two guarded ``driver.quit()`` calls disappeared.

Documented decisions (each commented and tested in
``tests/test_scraper_disco.py``):

1. Page 1 is NEVER collected — a legacy quirk kept verbatim. The paging
   loop starts at ``?page=2`` and the page-1 HTML the driver loaded is
   never parsed, so page 1's products are missing from every Disco
   scrape. A mechanical port must not silently change the collected
   data; fixing this quirk is a separate follow-up that must be
   validated against a real run before it lands.
2. Unexpected errors propagate instead of being swallowed. The legacy
   outer ``except Exception`` printed and returned, so a broken run
   looked successful. The ported run lets them escape — the scraper
   manager marks the run ``failed``. The legacy per-page ``try/except``
   (print, report, continue) is kept.
3. The never-executed ``arender(sleep=8)`` call is deleted, not
   replaced: it was never awaited, so it never ran (K-18).
"""

from __future__ import annotations

import json

from bs4 import BeautifulSoup

from api.helpers import name_parse
from api.scrapers.base import BaseScraper, ScrapeContext

# Selenium's ``webdriver.common.by.By.CLASS_NAME`` is the plain string
# "class name"; the scraper contract keeps scrapers selenium-import-free
# (the driver arrives from ctx.browser()), so the locator is spelled out.
BY_CLASS_NAME = "class name"


class ScraperDisco(BaseScraper):
    """Scrapes Disco's almacen category via a Chrome driver + json-LD."""

    slug = "disco"
    label = "Disco"
    categories = ("almacen",)

    # The legacy hardcoded 14-subcategory list, copied verbatim.
    SUBCATEGORIES = (
        "aceites-y-vinagres", "aceitunas-y-encurtidos", "aderezos",
        "arroz-y-legumbres", "caldos-sopas-y-pure", "conservas",
        "desayuno-y-merienda", "golosinas-y-chocolates", "sin-tacc",
        "panificados",
        "para-preparar", "pastas-secas-y-salsas", "sal-pimienta-y-especias",
        "snacks")

    def run(self, ctx: ScrapeContext) -> None:
        # A stop requested before the run touches the network keeps it inert
        # (the shared pre-cancelled contract guard; the legacy built the
        # driver first and only stopped inside the page loop).
        if ctx.should_stop():
            return
        # No legacy outer try/except here (decision 2): unexpected errors
        # propagate so the manager marks the run failed instead of letting
        # a broken run look successful.
        with ctx.browser() as driver:
            driver.maximize_window()
            driver.implicitly_wait(50)

            for seccion in self.SUBCATEGORIES:
                jsondata = []  # Reset jsondata for each subcategory
                ctx.report(f"Scrapeando subcategoría: {seccion}")

                # SCRAP DE SECCION
                driver.get("https://www.disco.com.ar/almacen/" + seccion)
                driver.execute_script(
                    "window.scrollTo(0, document.body.scrollHeight/2);")
                # driver.switch_to.window(driver.current_window_handle)
                if ctx.sleep(5):
                    # A stop raised during the wait ends the run cleanly:
                    # nothing was collected for this subcategory yet.
                    break

                # LEO EL TOTAL DE LA SECCION
                total = int(driver.find_element(
                    BY_CLASS_NAME,
                    "vtex-search-result-3-x-totalProducts--layout"
                ).text.split(" ")[0])

                if (total == 0):
                    print(f"No hay productos en {seccion}, continuando...")
                    continue

                print(f"Total de productos en {seccion}: {total}")

                # Scrapear todas las páginas de esta subcategoría.
                #
                # Decision 1 (legacy quirk, kept): the loop starts at page 2
                # and the page-1 HTML the driver just loaded is never
                # parsed, so page 1's products are missing from every Disco
                # scrape. A mechanical port must not silently change the
                # collected data; fixing this needs validation against a
                # real run (separate follow-up, not part of T9).
                for i in range(2, int((total/20))+1):
                    if ctx.should_stop():
                        break

                    try:
                        ctx.report(f"{seccion} - página {i}")
                        print(f'scraping data from Disco - '
                              f'{seccion} pagina: {i}')

                        url = 'https://www.disco.com.ar/almacen/' \
                            + seccion + '?page=' + str(i)
                        response = ctx.http.get(url)
                        # -- get data and parse
                        soup = BeautifulSoup(response.text, 'html.parser')

                        anchors = soup.find_all(
                            'div', class_='flex flex-column min-vh-100 w-100')
                        if (len(anchors) > 0):
                            if (anchors[0].next.name != 'script'):
                                print("No se encontró script en la página")
                                continue
                            # for a in anchors:
                            item = anchors[0].next.contents[0]
                            jsonitem = json.loads(item)

                            for jsonitemi in jsonitem["itemListElement"]:
                                try:
                                    if ("name" in jsonitemi["item"]):
                                        parsedNameUnidad = name_parse(
                                            jsonitemi["item"]["name"])
                                        jsonitea = {
                                            "supermercado": "Disco",
                                            "name": parsedNameUnidad['name'],
                                            "unidad":
                                                parsedNameUnidad['unidad'],
                                            "brand":
                                                jsonitemi["item"]["brand"][
                                                    "name"],
                                            "sku": jsonitemi["item"]["sku"],
                                            "price": jsonitemi["item"][
                                                "offers"]["lowPrice"]}
                                        if not any(
                                                element['name'] in
                                                jsonitea['name']
                                                for element in jsondata):
                                            jsondata.append(jsonitea)
                                except Exception:
                                    print("Error parsing data from jsonItems")
                                    continue
                        else:
                            print(f"No se encontraron elementos "
                                  f"en la página {i}")
                            continue

                    except Exception as ex:
                        print(f"Error al cargar la pagina {i}: {ex}")
                        ctx.report(f"Error al cargar la pagina: {i}")
                        continue

                # Guardar datos de esta subcategoría en MongoDB
                if jsondata:
                    jsondata.sort(key=lambda x: x["name"])
                    ctx.save(jsondata, categoria=seccion)
                    print(f"Procesada subcategoría {seccion} "
                          f"con {len(jsondata)} productos")
                else:
                    print(f"No se obtuvieron productos para {seccion}")

            ctx.report("PROCESO TERMINADO - Todas las subcategorías procesadas")
            print("Proceso Disco terminado OK")
