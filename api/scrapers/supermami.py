"""SuperMami scraper, ported to the scraper contract (T7).

Mechanical port of ``api.scrapers.scrap_supermami`` (the byte-identical
legacy reference, deleted in T14): URLs, selectors, the gtag
``view_item_list`` extraction and the stored keys are unchanged. Only the
plumbing moved to the contract: ``notifyStatus`` became ``ctx.report``,
``save_to_mongodb`` became ``ctx.save`` and the never-awaited
``arender(sleep=4)`` statements were dropped (they never executed, K-18).
SuperMami needs no browser: it scrapes plain GET responses only.
"""

from __future__ import annotations

import json

from bs4 import BeautifulSoup

from api.helpers import name_parse
from api.scrapers.base import BaseScraper, ScrapeContext

# The page loop is capped at two pages by a literal in the legacy code
# (``range(1, 3)``). Lifting the cap is a separate follow-up, not part of a
# mechanical port.
MAX_PAGES = 2


class ScraperSuperMami(BaseScraper):
    """Scrapes SuperMami's almacen category with plain HTTP only.

    ``categories`` is empty: the legacy route's ``param`` was never used,
    so the category query value is validated as "no filter".
    """

    slug = "supermami"
    label = "SuperMami"
    categories = ()

    def run(self, ctx: ScrapeContext) -> None:
        jsonData = []
        # A stop requested before the run touches the network keeps it inert
        # (the shared pre-cancelled contract guard).
        if ctx.should_stop():
            return
        url = 'https://www.supermami.com.ar/super/categoria/supermami-almacen/_/N-1tjm8rd?Nf=product.endDate%7CGTEQ+1.6723584E12%7C%7Cproduct.startDate%7CLTEQ+1.6723584E12&No=36'  # -- set url
        response = ctx.http.get(url)
        # -- get data and parse
        soup = BeautifulSoup(response.text, 'html.parser')
        total = int(soup.find_all('p', class_='txt-result')
                    [0].findAll("strong")[2].text)
        print('Total de paginas SuperMami :' + str(total))
        productos = soup.find_all('div', class_='product')
        if (len(productos) > 0):
            print('scraping data from SuperMami')

            totalPages = round(total/36)

            countPages = 0
            for page in range(1, MAX_PAGES + 1):
                if ctx.should_stop():
                    break

                ctx.report(f"página {page}")

                print('scraping data from SuperMami pagina:' + str(page))
                url = 'https://www.supermami.com.ar/super/categoria/supermami-almacen/_/N-1tjm8rd?Nf=product.endDate%7CGTEQ+1.6723584E12%7C%7Cproduct.startDate%7CLTEQ+1.6723584E12&No=' + \
                    str(countPages) + '&Nr=AND%28product.disponible%3ADisponible%2Cproduct.language%3Aespa%C3%B1ol%2Cproduct.priceListPair%3AsalePrices_listPrices%2COR%28product.siteId%3AsuperSite%29%29&Nrpp=36'  # -- set url
                response = ctx.http.get(url)
                # -- get data and parse
                soup = BeautifulSoup(response.text, 'html.parser')

                # Find the script tag containing "gtag('event', 'view_item_list',"
                script_tag = soup.find(
                    'script',
                    text=lambda t: t and "gtag('event', 'view_item_list'," in t)

                # Extract the JSON data inside gtag function call
                json_text = script_tag.string.strip().split(
                    'gtag(\'event\', \'view_item_list\',')[-1].strip()[:-2]

                # Parse the JSON data
                data = json.loads(json_text)
                productos = data['items']
                if (len(productos) > 0):
                    for jsonItemList in productos:
                        parsedNameUnidad = name_parse(
                            jsonItemList['name'])
                        item = {
                            "supermercado": "SuperMami",
                            "name": parsedNameUnidad['name'],
                            "unidad": parsedNameUnidad['unidad'],
                            "brand": jsonItemList['brand'],
                            "price": jsonItemList['price']}
                        jsonData.append(item)  # -- append item to json
                else:
                    # Legacy quirk preserved: an empty page hit `continue`,
                    # which skipped the countPages increment below, so the
                    # next iteration requested the SAME No= offset again.
                    continue
                countPages = countPages + 36

            jsonData.sort(key=lambda x: x["name"])
            ctx.save(jsonData)

            ctx.report(f"PROCESO TERMINADO CON {len(jsonData)} productos")
            print("Proceso Mami termino OK, con " +
                  str(jsonData.__len__()) + " productos")
