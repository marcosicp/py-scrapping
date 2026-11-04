"""HiperLibertad scraper, ported to the scraper contract (T8).

A mechanical port of the original requests-only module (deleted in T14): the
hardcoded 14-subcategory list, the VTEX search URL with its 50-item
``_from``/``_to`` paging, ``name_parse`` and the stored keys are unchanged.
Only the plumbing moved to the contract: progress reports go through
``ctx.report``, page fetches through ``ctx.http.get``, waits through
``ctx.sleep``, the stop check through ``ctx.should_stop()`` and persistence
through ``ctx.save`` (saving one subcategory at a time).

Two deliberate, tested fixes:

1. The original guard ``response.status_code == 200 | response.status_code
   == 206`` chained ``==`` with the bitwise OR and was False for every
   status, so the pre-port scraper stored nothing ever. The port accepts
   both success codes with ``in (200, 206)``; any other status keeps the
   historical behavior (print the error and break).
2. The legacy run built a Selenium Chrome driver and never used it in the
   API path. The port opens NO browser: it scrapes plain GET responses
   from the VTEX JSON API only.
"""

from __future__ import annotations

from api.helpers import name_parse
from api.scrapers.base import BaseScraper, ScrapeContext


class ScraperHiperLibertad(BaseScraper):
    """Scrapes HiperLibertad's almacen category through the VTEX JSON API."""

    slug = "hiperlibertad"
    label = "HiperLibertad"
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
        # (the shared pre-cancelled contract guard).
        if ctx.should_stop():
            return
        try:
            categoria = self.validate_category(ctx.category) \
                or self.categories[0]
            ctx.report(f"Scrapeando categoria: {categoria}")

            for subCategory in self.SUBCATEGORIES:
                if ctx.should_stop():
                    break

                jsonData = self._scrape_subcategory(ctx, categoria,
                                                    subCategory)

                # Save to the repository when the subcategory is completed.
                if jsonData:
                    count = ctx.save(jsonData, categoria=categoria,
                                     subcategoria=subCategory)
                    if count:
                        print(f"Saved {len(jsonData)} HiperLibertad products"
                              f" from {categoria}/{subCategory} to MongoDB")

            ctx.report("PROCESO TERMINADO")
            print("Proceso HiperLibertad terminado OK")

        except Exception as e:
            print(f"Error general en scraper HiperLibertad: {e}")

    def _scrape_subcategory(self, ctx: ScrapeContext, categoria: str,
                            subCategory: str) -> list[dict]:
        """Page one subcategory through the VTEX search API."""
        jsonData: list[dict] = []
        pageIncrement = 0

        try:
            ctx.report(f"Inicio Scrap sub-categoria: {subCategory}")

            while not ctx.should_stop():
                ctx.report(
                    f"{subCategory} - página {pageIncrement//50 + 1}")

                url = (f'https://www.hiperlibertad.com.ar/api/'
                       f'catalog_system/pub/products/search/{categoria}/'
                       f'{subCategory}?O=OrderByPriceASC&_from={pageIncrement}'
                       f'&_to={pageIncrement+49}&ft&sc=1')

                try:
                    response = ctx.http.get(url, timeout=30)
                    # Fix (T8, tested): the legacy guard ``response.
                    # status_code == 200 | response.status_code == 206``
                    # chained ``==`` with the bitwise OR and was False for
                    # every status, so the legacy scraper stored nothing.
                    if response.status_code in (200, 206):
                        jsonItems = response.json()

                        if len(jsonItems) == 0:
                            break  # No more products

                        for jsonItemList in jsonItems:
                            try:
                                if "productName" in jsonItemList:
                                    parsedNameUnidad = name_parse(
                                        jsonItemList["productName"])

                                    # Get price from offers
                                    price = 0
                                    if ("items" in jsonItemList and
                                        len(jsonItemList["items"]) > 0 and
                                        "sellers" in
                                            jsonItemList["items"][0] and
                                        len(
                                            jsonItemList["items"][0]
                                            ["sellers"]) > 0):
                                        price = jsonItemList["items"][0][
                                            "sellers"][0][
                                            "commertialOffer"]["Price"]

                                    jsonItemFormatted = {
                                        "supermercado": "HiperLibertad",
                                        "name":
                                            parsedNameUnidad['name'],
                                        "unidad":
                                            parsedNameUnidad['unidad'],
                                        "brand":
                                            jsonItemList.get("brand", ""),
                                        "sku":
                                            jsonItemList.get("sku", ""),
                                        "price": price
                                    }

                                    # Check for duplicates
                                    if not any(
                                            element['name'] in
                                            jsonItemFormatted['name']
                                            for element in jsonData):
                                        jsonData.append(jsonItemFormatted)
                            except Exception as item_error:
                                print(f"Error processing item: "
                                      f"{item_error}")
                                continue

                        pageIncrement += 50
                        # Honour a stop raised during the rate-limiting
                        # sleep (the legacy slept unconditionally here).
                        if ctx.sleep(1):
                            break
                    else:
                        print(f"Error API response: "
                              f"{response.status_code}")
                        break

                except Exception as api_error:
                    print(f"Error calling API: {api_error}")
                    break

            jsonData.sort(key=lambda x: x["name"])
            print(f"Procesada subcategoría {subCategory} con "
                  f"{len(jsonData)} productos")
            return jsonData

        except Exception as ex:
            print(f"Error en scraper al traer productos de {subCategory}: "
                  f"{ex}")
            ctx.report(f"Error en scraper al traer productos de "
                       f"{subCategory}")
            return []
