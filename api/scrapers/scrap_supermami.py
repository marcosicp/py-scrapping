
from bs4 import BeautifulSoup
from requests_html import HTMLSession
import json
import requests
import time
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from api.helpers import name_parse
from flask import current_app

from api.sockets import notifyStatus

_hTMLSession = HTMLSession()


class ScrapeSuperMami:
    activeSupermami = True

    def find_gtag_script(tag):
        return tag.name == 'script' and 'gtag(' in tag.string
                
    def scrape_supermami_stop(self):
        self.activeSupermami = False

    def scrape_supermami(self, param):
        jsonData = []
        url = 'https://www.supermami.com.ar/super/categoria/supermami-almacen/_/N-1tjm8rd?Nf=product.endDate%7CGTEQ+1.6723584E12%7C%7Cproduct.startDate%7CLTEQ+1.6723584E12&No=36'  # -- set url
        response = _hTMLSession.get(url)
        response.html.arender(sleep=4)
        # -- get data and parse
        soup = BeautifulSoup(response.text, 'html.parser')
        total = int(soup.find_all('p', class_='txt-result')
                    [0].findAll("strong")[2].text)
        print('Total de paginas SuperMami :' + str(total))
        productos = soup.find_all('div', class_='product')
        if (len(productos) > 0):
            print('scraping data from SuperMami')
            # for a in productos:
            #     item = {"supermercado": "SuperMami",
            #             "name": a.find("div", {"class": "description limitRow tooltipHere"}).text,

            #             "price":  a.find(
            #         "div", {"class": "precio-unidad"}).text.replace("$", "").replace("x un", "").replace("\t", "").replace("\r", "").replace("\n", "").replace("..", "")}
            #     jsonData.append(item)  # -- append item to json

            totalPages = round(total/36)
            countPages = 0
            for page in range(1, 3):
                notifyStatus("scraping-message-supermami", page)

                print('scraping data from SuperMami pagina:' + str(page))
                url = 'https://www.supermami.com.ar/super/categoria/supermami-almacen/_/N-1tjm8rd?Nf=product.endDate%7CGTEQ+1.6723584E12%7C%7Cproduct.startDate%7CLTEQ+1.6723584E12&No=' + \
                    str(countPages) + '&Nr=AND%28product.disponible%3ADisponible%2Cproduct.language%3Aespa%C3%B1ol%2Cproduct.priceListPair%3AsalePrices_listPrices%2COR%28product.siteId%3AsuperSite%29%29&Nrpp=36'  # -- set url
                response = _hTMLSession.get(url)
                response.html.arender(sleep=4)
                # -- get data and parse
                soup = BeautifulSoup(response.text, 'html.parser')

                                
                # Find the script tag containing "gtag('event', 'view_item_list',"
                script_tag = soup.find('script', text=lambda t: t and "gtag('event', 'view_item_list'," in t)

                # Extract the JSON data inside gtag function call
                json_text = script_tag.string.strip().split('gtag(\'event\', \'view_item_list\',')[-1].strip()[:-2]

                # Parse the JSON data
                data = json.loads(json_text)
                productos = data['items']
                if (self.activeSupermami):
                    if (len(productos) > 0):
                        for jsonItemList in productos:
                            parsedNameUnidad = name_parse(jsonItemList['name'])
                            item = {
                                "supermercado": "SuperMami",
                                "name": parsedNameUnidad['name'],
                                "unidad": parsedNameUnidad['unidad'],
                                # "sku": parsedNameUnidad['sku'],
                                "brand": jsonItemList['brand'],
                                "price":  jsonItemList['price']}
                            jsonData.append(item)  # -- append item to json
                    else:
                        continue
                else:
                    break
                countPages = countPages+36

            jsonData.sort(key=lambda x: x["name"])
            # with open('supermami.json', 'w') as outfile:
            #     # -- save jsondata to '.json' file
            #     json.dump(jsonData, outfile)
                
            # Save to MongoDB database
            try:
                # Access lalistitadev database and productos collection
                mongodb_client = current_app.mongodb_client
                database = mongodb_client.lalistitadev
                collection = database.productos
                
                # Clear existing SuperMami data for fresh scrape
                collection.delete_many({"supermercado": "SuperMami"})
                
                # Add timestamp to each product
                for product in jsonData:
                    product['scraped_at'] = datetime.utcnow()
                
                # Insert all products
                if jsonData:
                    collection.insert_many(jsonData)
                    print(f"Saved {len(jsonData)} SuperMami products to MongoDB (lalistitadev.productos)")
                    
            except Exception as e:
                print(f"Error saving to MongoDB: {e}")
                
            notifyStatus("scraping-message-supermami", "PROCESO TERMINADO CON " +
                         str(jsonData.__len__()) + " productos")
            print("Proceso Mami termino OK, con " +
                  str(jsonData.__len__()) + " productos")
            # return render_template('index.html', todos=jsonData, carre=0, mami=jsonData.__len__(), hiper=0, disco=0)
            # save jsonData to database
            