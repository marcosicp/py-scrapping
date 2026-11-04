"""Carrefour scraper, ported to the scraper contract (T10).

A mechanical port of the original browser-driven module (deleted
in T14). The original implementation has two genuinely different collection
paths and both are kept:

- **Path A — a category was requested** (``ctx.category is not None``): the
  original ``param`` branch. Page ``?page=i`` documents come from the embedded
  ``<template data-varname="__STATE__">`` json-LD extraction over the shared
  HTTP session, and the stored keys are ``supermercado/name/brand/sku/price``
  with NO ``unidad`` and NO ``name_parse`` — an original omission kept verbatim
  (fixing it would silently change the collected data).
- **Path B — no category** (all categories): the original ``else`` branch. Each
  subcategory is visited through the Chrome driver, the products are read
  from the ``render-provider`` script tag and go through ``name_parse`` (so
  they DO carry ``unidad``), and each category is saved once after all its
  subcategories.

Plumbing moved to the contract: progress reports go through ``ctx.report``,
the stop check through ``ctx.should_stop()``, waits through ``ctx.sleep``,
the driver comes from ``ctx.browser()`` (replacing the two guarded
``driver.quit()`` calls) and persistence through ``ctx.save``.

Documented decisions (each commented and tested in
``tests/test_scraper_carrefour.py``):

1. An empty result never wipes the slice. Legacy Path A called
   ``save_to_mongodb`` unconditionally, which deleted the category and
   inserted nothing when the scrape produced zero products. ``ctx.save`` is a
   no-op on an empty list (the same D6 guarantee that fixed K-8), so the port
   keeps the stored data instead.
2. Errors surface. The port keeps the legacy per-subcategory handlers exactly
   (print, report where the legacy reported, continue) and lets anything else
   propagate so the manager marks the run ``failed``.
3. The never-executed ``arender(sleep=8)`` statements are deleted, not
   replaced: they were never awaited, so they never ran (K-18).

Two more original quirks of Path A the port reshaped (commented at the
code, pinned by the behavior tests):

- The legacy Path A visited page 1 through the Chrome driver to read the
  product total. The ported Path A builds NO browser: that visit became a
  plain ``ctx.http.get`` of the same URL and the total is read from the
  response HTML, so the URL sequence stays ``base, ?page=1, ?page=2, ...``.
- The legacy Path A crashed before scraping anything: it concatenated the
  whole category dict into its first progress message
  (``"Scrapeando categoria: " + categoryRequested`` → TypeError). The port
  keeps the message text using the category slug.
"""

from __future__ import annotations

import json

from bs4 import BeautifulSoup

from api.helpers import name_parse
from api.scrapers.base import BaseScraper, ScrapeContext

# Selenium's ``By.CLASS_NAME``/``By.XPATH`` are the plain strings
# "class name"/"xpath"; the scraper contract keeps scrapers
# selenium-import-free (the driver arrives from ctx.browser()), so the
# locators are spelled out.
BY_CLASS_NAME = "class name"
BY_XPATH = "xpath"

BASE_URL = "https://www.carrefour.com.ar/"
SCROLL_SCRIPT = "window.scrollTo(0, document.body.scrollHeight);"
RENDER_DIV_XPATH = '//div[@class="render-provider"]'
SCRIPT_XPATH = ".//script"

# The legacy hardcoded total-product DOM classes, one per collection path.
TOTAL_CLASS_PATH_A = "valtech-carrefourar-search-result-0-x-totalProducts--layout"
TOTAL_CLASS_PATH_B = "valtech-carrefourar-search-result-3-x-totalProducts--layout"


class ScraperCarrefour(BaseScraper):
    """Scrapes Carrefour's two categories through both collection paths."""

    slug = "carrefour"
    label = "Carrefour"
    categories = ("almacen", "desayuno-y-merienda")

    # The legacy hardcoded category/subcategory structure, copied verbatim.
    CATEGORIES = (
        {"categoria": "almacen", "subcategorias": [
            "aceites-y-vinagres", "arroz-y-legumbres", "caldos-sopas-y-pure",
            "enlatados-y-conservas", "harinas", "pastas-secas",
            "reposteria-y-postres", "sal-aderezos-y-saborizadores", "snacks"]},
        {"categoria": "desayuno-y-merienda", "subcategorias": [
            "azucar-y-endulzantes", "budines-y-magdalenas", "cafe",
            "cereales-y-barritas", "galletitas-bizcochitos-y-tostadas",
            "golosinas-y-chocolates", "infusiones",
            "mermeladas-y-otros-dulces", "yerba"]},
    )

    def run(self, ctx: ScrapeContext) -> None:
        # A stop requested before the run touches the network keeps it inert
        # (the shared pre-cancelled contract guard).
        if ctx.should_stop():
            return
        category = self.validate_category(ctx.category)
        # An unknown category never reaches run() (the manager validates and
        # answers 400); if one does, InvalidCategory propagates (decision 2)
        # instead of the legacy fall-through that ended the run silently.
        if category is not None:
            self._scrape_requested_category(ctx, category)
            return
        with ctx.browser() as driver:
            self._scrape_all_categories(ctx, driver)
        # Path B only: the legacy returned before this block on the param
        # path, so Path A ends without the final report (kept verbatim).
        ctx.report("PROCESO TERMINADO")
        print("Proceso Carrefour terminado")

    # -- Path A: the legacy ``param`` branch ---------------------------------

    def _scrape_requested_category(self, ctx: ScrapeContext,
                                   category: str) -> None:
        """Scrape one requested category over the HTTP session (no browser)."""
        jsonData = []

        categoryRequested = next(
            (x for x in self.CATEGORIES if x["categoria"] == category), None)

        # The legacy concatenated the whole dict here ("Scrapeando categoria: "
        # + categoryRequested → TypeError) and crashed before scraping
        # anything; the port keeps the message text with the category slug.
        ctx.report("Scrapeando categoria: " + categoryRequested["categoria"])
        for subCategory in categoryRequested["subcategorias"]:
            try:
                ctx.report("Inicio Scrap sub-categoria: " + subCategory)
                # The legacy visited page 1 through the Chrome driver to read
                # the total; the ported Path A builds no browser, so the same
                # URL is fetched over the shared HTTP session and the total
                # is read from the response HTML.
                response = ctx.http.get(BASE_URL + categoryRequested["categoria"]
                                        + "/" + subCategory)
                ctx.sleep(10)
                total = int(BeautifulSoup(response.text, 'html.parser').find(
                    class_=TOTAL_CLASS_PATH_A).text.split(" ")[0])
                if (total == 0):
                    # Legacy abort kept verbatim: the WHOLE run ends here,
                    # before any save and before the other subcategories.
                    return

                for i in range(1, int((total/16))):
                    if ctx.should_stop():
                        break

                    url = BASE_URL + categoryRequested["categoria"] + '/' \
                        + subCategory + '?page=' + str(i)  # -- set url
                    response = ctx.http.get(url)
                    # -- get data and parse
                    soup = BeautifulSoup(response.text, 'html.parser')

                    anchors = soup.find_all(
                        'template', {'data-type': 'json',
                                     'data-varname': '__STATE__'})
                    if (len(anchors) > 0):
                        if (anchors[0].next.name != 'script'):
                            break
                        # for a in anchors:
                        anchorContent = anchors[0].next.contents[0]
                        jsonItems = json.loads(anchorContent)

                        for item in jsonItems["itemListElement"]:
                            try:
                                if ("name" in item["item"]):
                                    # Legacy omission kept: no ``name_parse``
                                    # here, Path A stores the raw product
                                    # name and has no ``unidad`` key.
                                    jsonFormatted = {"supermercado": "Carrefour",
                                                     "name": item["item"]["name"],
                                                     "brand": item["item"]["brand"]["name"],
                                                     "sku": item["item"]["sku"],
                                                     "price": item["item"]["offers"]["lowPrice"]}
                                    if not any(element['name'] in jsonFormatted['name']
                                               for element in jsonData):
                                        print('Chirp')
                                        jsonData.append(jsonFormatted)
                                    # attempt = 0
                            except Exception:
                                print("Error al construir array")
                                continue

                    ctx.report(str(i) + "-" + str(total))

            except Exception:
                # Legacy per-subcategory handler kept exactly (print +
                # continue); Path A never reported this error.
                print("Error en scraper al traer productos")
                continue

        # Decision 1: the legacy called save_to_mongodb unconditionally,
        # which deleted the category and inserted nothing when jsonData was
        # empty. ctx.save is a no-op on an empty list, so an empty result
        # keeps the stored slice instead of wiping it.
        ctx.save(jsonData, categoria=categoryRequested["categoria"])

    # -- Path B: the legacy ``else`` branch -----------------------------------

    def _scrape_all_categories(self, ctx: ScrapeContext, driver) -> None:
        """Scrape every category through the Chrome driver."""
        for categoria in self.CATEGORIES:
            jsonData = []  # Reset jsonData for each category
            ctx.report("Scrapeando categoria: " + categoria["categoria"])
            for subCategory in categoria["subcategorias"]:
                try:
                    ctx.report("Inicio Scrap sub-categoria: " + subCategory)
                    driver.get(BASE_URL + categoria["categoria"] + "/"
                               + subCategory)
                    driver.execute_script(SCROLL_SCRIPT)
                    driver.switch_to.window(driver.current_window_handle)
                    ctx.sleep(10)
                    total = int(driver.find_element(
                        BY_CLASS_NAME, TOTAL_CLASS_PATH_B).text.split(" ")[0])
                    if (total == 0):
                        continue  # Continue with next subcategory instead of return

                    for i in range(1, int((total/16))):
                        if ctx.should_stop():
                            break

                        url = BASE_URL + categoria["categoria"] + '/' \
                            + subCategory + '?page=' + str(i)  # -- set url
                        driver.get(url)
                        ctx.sleep(10)
                        # -- Find the <div> element with class "render"
                        # -- and the <script> tag within it
                        render_div = driver.find_element(BY_XPATH,
                                                         RENDER_DIV_XPATH)
                        script_element = render_div.find_element(BY_XPATH,
                                                                 SCRIPT_XPATH)
                        script_content = script_element.get_attribute(
                            'innerHTML')
                        json_data = json.loads(script_content)

                        if (len(json_data) > 0):
                            jsonItems = json_data

                            for item in jsonItems["itemListElement"]:
                                try:
                                    parsedNameUnidad = name_parse(
                                        item["item"]["name"])
                                    jsonFormatted = {"supermercado": "Carrefour",
                                                     "name": parsedNameUnidad['name'],
                                                     "unidad": parsedNameUnidad['unidad'],
                                                     "brand": item["item"]["brand"]["name"],
                                                     "sku": item["item"]["sku"],
                                                     "price": item["item"]["offers"]["lowPrice"]}
                                    if not any(element['name'] in jsonFormatted['name']
                                               for element in jsonData):
                                        jsonData.append(jsonFormatted)
                                    # attempt = 0
                                except Exception as ex:
                                    ctx.report("Error al construir array de "
                                               "subcategoria: " + subCategory)
                                    print("Error al construir array")
                                    continue

                        ctx.report(str(i) + "-" + str(total))

                except Exception:
                    # Legacy per-subcategory handler kept exactly (report +
                    # print + continue).
                    ctx.report("Error en scraper al traer productos")
                    print("Error en scraper al traer productos")
                    continue

            # Save to MongoDB when each category is completed
            if jsonData:
                ctx.save(jsonData, categoria=categoria["categoria"])
