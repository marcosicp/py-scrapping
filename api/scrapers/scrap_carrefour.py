from bs4 import BeautifulSoup
from requests_html import HTMLSession
import json
import requests
import time
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from api.helpers import name_parse
from flask import current_app

from api.sockets import notifyStatus
# from pymongo.mongo_client import MongoClient
# from pymongo.server_api import ServerApi

# # Create a new client and connect to the server
# client = MongoClient(uri, server_api=ServerApi('1'))

_hTMLSession = HTMLSession()



class ScrapeCarrefour:
    activeCarre = True

    def scrape_carrefour_stop(self):
        # global activeCarre
        self.activeCarre = False

    def save_to_mongodb(self, jsonData, category_name):
        """Save scraped data to MongoDB"""
        try:
            # Access lalistitadev database and productos collection
            mongodb_client = current_app.mongodb_client
            database = mongodb_client.lalistitadev
            collection = database.productos
            
            # Clear existing Carrefour data for this category
            collection.delete_many({"supermercado": "Carrefour", "categoria": category_name})
            
            # Add timestamp and category to each product
            for product in jsonData:
                product['scraped_at'] = datetime.utcnow()
                product['categoria'] = category_name
            
            # Insert all products in one operation
            if jsonData:
                collection.insert_many(jsonData)
                print(f"Saved {len(jsonData)} Carrefour products from {category_name} to MongoDB")
                notifyStatus("scraping-message-carrefour", f"Guardados {len(jsonData)} productos de {category_name} en base de datos")
                return True
                
        except Exception as e:
            print(f"Error saving Carrefour {category_name} data to MongoDB: {e}")
            notifyStatus("scraping-message-carrefour", f"Error al guardar {category_name} en base de datos")
            return False

    # CON SELENIUM

    def scrape_carrefour(self, param):
        
        jsonData = []

        # buscar secciones y subsecciones dinamicamente
        categories = [{"categoria": "almacen", "subcategorias": ["aceites-y-vinagres", "arroz-y-legumbres", "caldos-sopas-y-pure",
                                                                 "enlatados-y-conservas", "harinas", "pastas-secas", "reposteria-y-postres",
                                                                 "sal-aderezos-y-saborizadores", "snacks"]},
                      {"categoria": "desayuno-y-merienda", "subcategorias": ["azucar-y-endulzantes", "budines-y-magdalenas", "cafe", "cereales-y-barritas",
                                                                             "galletitas-bizcochitos-y-tostadas", "golosinas-y-chocolates", "infusiones", "mermeladas-y-otros-dulces", "yerba"]}]

        service = Service('/usr/local/bin/chromedriver-141')
        options = webdriver.ChromeOptions()
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        # options.add_argument('--headless')  # Uncomment for background execution
        driver = webdriver.Chrome(service=service, options=options)

        if (param is not None and param != ""):
            categoryRequested = next(
                (x for x in categories if x["categoria"] == param), None)

            if (categoryRequested is not None):
                notifyStatus("scraping-message-carrefour",
                             "Scrapeando categoria: " + categoryRequested)
                for subCategory in categoryRequested["subcategorias"]:
                    try:
                        notifyStatus("scraping-message-carrefour",
                                     "Inicio Scrap sub-categoria: " + subCategory)
                        driver.get("https://www.carrefour.com.ar/" +
                                   categoryRequested["categoria"] + "/" + subCategory)
                        driver.execute_script(
                            "window.scrollTo(0, document.body.scrollHeight);")
                        driver.switch_to.window(driver.current_window_handle)
                        time.sleep(10)
                        total = int(driver.find_element(
                            By.CLASS_NAME, "valtech-carrefourar-search-result-0-x-totalProducts--layout").text.split(" ")[0])
                        if (total == 0):
                            return

                        for i in range(1, int((total/16))):
                            if not (self.activeCarre):
                                break

                            url = 'https://www.carrefour.com.ar/' + categoryRequested["categoria"] + '/' + subCategory + '?page=' + \
                                str(i)  # -- set url
                            response = _hTMLSession.get(url)
                            response.html.arender(sleep=8)
                            # -- get data and parse
                            soup = BeautifulSoup(response.text, 'html.parser')

                            anchors = soup.find_all(
                                'template', {'data-type': 'json', 'data-varname': '__STATE__'})
                            if (len(anchors) > 0):
                                if (anchors[0].next.name != 'script'):
                                    flag = False
                                    break
                                # for a in anchors:
                                anchorContent = anchors[0].next.contents[0]
                                jsonItems = json.loads(anchorContent)

                                for item in jsonItems["itemListElement"]:
                                    try:
                                        if ("name" in item["item"]):
                                            jsonFormatted = {"supermercado": "Carrefour",
                                                             "name": item["item"]["name"],
                                                             "brand": item["item"]["brand"]["name"],
                                                             "sku": item["item"]["sku"],
                                                             "price": item["item"]["offers"]["lowPrice"]}
                                            if not any(element['name'] in jsonFormatted['name'] for element in jsonData):
                                                print('Chirp')
                                                jsonData.append(jsonFormatted)
                                            # attempt = 0
                                    except Exception:
                                        # notifyStatus("scraping-message-carrefour", "Error al construir array de subcategoria: " + subcategoria)
                                        print("Error al construir array")
                                        continue

                            notifyStatus("scraping-message-carrefour",
                                         str(i) + "-" + str(total))

                    except Exception:
                        # notifyStatus("scraping-message-carrefour", "Error en scraper al traer productos")
                        print("Error en scraper al traer productos")
                        continue
                
                # Save to MongoDB when category is completed
                self.save_to_mongodb(jsonData, categoryRequested["categoria"])
                
                # Close the driver
                try:
                    driver.quit()
                except:
                    pass
                
                return
        else:
            for categoria in categories:
                jsonData = []  # Reset jsonData for each category
                notifyStatus("scraping-message-carrefour",
                             "Scrapeando categoria: " + categoria["categoria"])
                for subCategory in categoria["subcategorias"]:
                    try:
                        notifyStatus("scraping-message-carrefour",
                                     "Inicio Scrap sub-categoria: " + subCategory)
                        driver.get("https://www.carrefour.com.ar/" +
                                   categoria["categoria"] + "/" + subCategory)
                        driver.execute_script(
                            "window.scrollTo(0, document.body.scrollHeight);")
                        driver.switch_to.window(driver.current_window_handle)
                        time.sleep(10)
                        total = int(driver.find_element(
                            By.CLASS_NAME, "valtech-carrefourar-search-result-3-x-totalProducts--layout").text.split(" ")[0])
                        if (total == 0):
                            continue  # Continue with next subcategory instead of return

                        for i in range(1, int((total/16))):
                            if not (self.activeCarre):
                                break

                            url = 'https://www.carrefour.com.ar/' + categoria["categoria"] + '/' + subCategory + '?page=' + \
                                str(i)  # -- set url
                            driver.get('https://www.carrefour.com.ar/' + categoria["categoria"] + '/' + subCategory + '?page=' +
                                       str(i))  # -- set url

                            time.sleep(10)
                            # Find the <div> element with class "render"
                            render_div = driver.find_element(
                                By.XPATH, ('//div[@class="render-provider"]'))

                            # # Find the <div> element with class "bg-base" within the render_div
                            # bg_base_div = render_div.find_element(By.XPATH, ('.//div[@class="vtex-store__template bg-base"]'))

                            # # Find another <div> element within the render_div
                            # another_div = render_div.find_element(By.XPATH, ('.//div[@class="flex flex-column min-vh-100 w-100"]'))

                            # Find the <script> tag within the render_div
                            script_element = render_div.find_element(
                                By.XPATH, ('.//script'))

                            # Extract the text content of the <script> tag
                            script_content = script_element.get_attribute(
                                'innerHTML')

                            # Parse the JSON data
                            json_data = json.loads(script_content)

                            if (len(json_data) > 0):
                                # if (anchors[0].next.name != 'script'):
                                #     flag = False
                                #     break
                                # for a in anchors:
                                # anchorContent = anchors[0].next.contents[0]
                                jsonItems = json_data

                                for item in jsonItems["itemListElement"]:
                                    try:
                                        # if ("name" in item):
                                        parsedNameUnidad = name_parse(
                                            item["item"]["name"])
                                        jsonFormatted = {"supermercado": "Carrefour",
                                                         "name": parsedNameUnidad['name'],
                                                         "unidad": parsedNameUnidad['unidad'],
                                                         "brand": item["item"]["brand"]["name"],
                                                         "sku": item["item"]["sku"],
                                                         "price": item["item"]["offers"]["lowPrice"]}
                                        if not any(element['name'] in jsonFormatted['name'] for element in jsonData):
                                            jsonData.append(jsonFormatted)
                                            # attempt = 0
                                    except Exception as ex:
                                        notifyStatus(
                                            "scraping-message-carrefour", "Error al construir array de subcategoria: " + subCategory)
                                        print("Error al construir array")
                                        continue

                            notifyStatus("scraping-message-carrefour",
                                         str(i) + "-" + str(total))
                        
                        
                        # with open('.carrefour/' + categoria["categoria"] + '/'+subCategory+'.json', 'w') as outfile:
                        #     json.dump(jsonData, outfile)
                        #     jsonData.clear()
                    except Exception:
                        notifyStatus("scraping-message-carrefour",
                                     "Error en scraper al traer productos")
                        print("Error en scraper al traer productos")
                        continue
                
                # Save to MongoDB when each category is completed
                if jsonData:
                    self.save_to_mongodb(jsonData, categoria["categoria"])
        
        # Close the driver
        try:
            driver.quit()
        except:
            pass
        
        notifyStatus("scraping-message-carrefour", "PROCESO TERMINADO")
        print("Proceso Carrefour terminado")
