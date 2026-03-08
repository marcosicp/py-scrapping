
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

_hTMLSession = HTMLSession()


class ScrapeHiperLibertad:
    activeHiperlibertad = True

    def scrape_hiperlibertad_stop(self):
        self.activeHiperlibertad = False

    def save_to_mongodb(self, jsonData, category_name, subcategory_name):
        """Save scraped data to MongoDB"""
        try:
            # Access lalistitadev database and productos collection
            mongodb_client = current_app.mongodb_client
            database = mongodb_client.lalistitadev
            collection = database.productos
            
            # Clear existing HiperLibertad data for this subcategory
            collection.delete_many({
                "supermercado": "HiperLibertad", 
                "categoria": category_name,
                "subcategoria": subcategory_name
            })
            
            # Add timestamp, category and subcategory to each product
            for product in jsonData:
                product['scraped_at'] = datetime.utcnow()
                product['categoria'] = category_name
                product['subcategoria'] = subcategory_name
            
            # Insert all products in one operation
            if jsonData:
                collection.insert_many(jsonData)
                print(f"Saved {len(jsonData)} HiperLibertad products from {category_name}/{subcategory_name} to MongoDB")
                notifyStatus("scraping-message-hiperlibertad", f"Guardados {len(jsonData)} productos de {subcategory_name} en base de datos")
                return True
                
        except Exception as e:
            print(f"Error saving HiperLibertad {category_name}/{subcategory_name} data to MongoDB: {e}")
            notifyStatus("scraping-message-hiperlibertad", f"Error al guardar {subcategory_name} en base de datos")
            return False

    def scrape_hiperlibertad(self, param):
        """Scrape HiperLibertad using API endpoints"""
        try:
            service = Service('/usr/local/bin/chromedriver-141')
            options = webdriver.ChromeOptions()
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--headless')  # Use headless for API calls
            driver = webdriver.Chrome(service=service, options=options)

            categories = [{"categoria": "almacen", "subcategorias": ["aceites-y-vinagres", "aceitunas-y-encurtidos", "aderezos",
                                                                     "arroz-y-legumbres", "caldos-sopas-y-pure", "conservas",
                                                                     "desayuno-y-merienda", "golosinas-y-chocolates", "sin-tacc", "panificados",
                                                                     "para-preparar", "pastas-secas-y-salsas", "sal-pimienta-y-especias", "snacks"]}]

            if (param is not None and param != ""):
                categoryRequested = next(
                    (x for x in categories if x["categoria"] == param), None)

                if (categoryRequested is not None):
                    notifyStatus("scraping-message-hiperlibertad",
                                 f"Scrapeando categoria: {categoryRequested['categoria']}")
                    
                    for subCategory in categoryRequested["subcategorias"]:
                        if not self.activeHiperlibertad:
                            break
                        
                        jsonData = self._scrape_subcategory(driver, categoryRequested["categoria"], subCategory)
                        
                        # Save to MongoDB when subcategory is completed
                        if jsonData:
                            self.save_to_mongodb(jsonData, categoryRequested["categoria"], subCategory)
            else:
                for categoria in categories:
                    notifyStatus("scraping-message-hiperlibertad",
                                f"Scrapeando categoria: {categoria['categoria']}")
                    
                    for subCategory in categoria["subcategorias"]:
                        if not self.activeHiperlibertad:
                            break
                        
                        jsonData = self._scrape_subcategory(driver, categoria["categoria"], subCategory)
                        
                        # Save to MongoDB when subcategory is completed
                        if jsonData:
                            self.save_to_mongodb(jsonData, categoria["categoria"], subCategory)

            # Close the driver
            try:
                driver.quit()
            except:
                pass

            notifyStatus("scraping-message-hiperlibertad", "PROCESO TERMINADO")
            print("Proceso HiperLibertad terminado OK")

        except Exception as e:
            print(f"Error general en scraper HiperLibertad: {e}")
            try:
                driver.quit()
            except:
                pass

    def _scrape_subcategory(self, driver, categoria, subCategory):
        """Helper method to scrape a specific subcategory"""
        jsonData = []
        pageIncrement = 0
        
        try:
            notifyStatus("scraping-message-hiperlibertad",
                        f"Inicio Scrap sub-categoria: {subCategory}")
            
            while self.activeHiperlibertad:
                notifyStatus("scraping-message-hiperlibertad", f"{subCategory} - página {pageIncrement//50 + 1}")
                
                # Use API endpoint approach
                url = f'https://www.hiperlibertad.com.ar/api/catalog_system/pub/products/search/{categoria}/{subCategory}?O=OrderByPriceASC&_from={pageIncrement}&_to={pageIncrement+49}&ft&sc=1'
                
                try:
                    response = requests.get(url, timeout=30)
                    if response.status_code == 200 | response.status_code == 206:
                        jsonItems = response.json()
                        
                        if len(jsonItems) == 0:
                            break  # No more products
                        
                        for jsonItemList in jsonItems:
                            try:
                                if "productName" in jsonItemList:
                                    parsedNameUnidad = name_parse(jsonItemList["productName"])
                                    
                                    # Get price from offers
                                    price = 0
                                    if ("items" in jsonItemList and 
                                        len(jsonItemList["items"]) > 0 and 
                                        "sellers" in jsonItemList["items"][0] and
                                        len(jsonItemList["items"][0]["sellers"]) > 0):
                                        price = jsonItemList["items"][0]["sellers"][0]["commertialOffer"]["Price"]
                                    
                                    jsonItemFormatted = {
                                        "supermercado": "HiperLibertad",
                                        "name": parsedNameUnidad['name'],
                                        "unidad": parsedNameUnidad['unidad'],
                                        "brand": jsonItemList.get("brand", ""),
                                        "sku": jsonItemList.get("sku", ""),
                                        "price": price
                                    }
                                    
                                    # Check for duplicates
                                    if not any(element['name'] in jsonItemFormatted['name'] for element in jsonData):
                                        jsonData.append(jsonItemFormatted)
                            except Exception as item_error:
                                print(f"Error processing item: {item_error}")
                                continue
                        
                        pageIncrement += 50
                        time.sleep(1)  # Rate limiting
                        
                    else:
                        print(f"Error API response: {response.status_code}")
                        break
                        
                except Exception as api_error:
                    print(f"Error calling API: {api_error}")
                    break
            
            jsonData.sort(key=lambda x: x["name"])
            print(f"Procesada subcategoría {subCategory} con {len(jsonData)} productos")
            return jsonData
            
        except Exception as ex:
            print(f"Error en scraper al traer productos de {subCategory}: {ex}")
            notifyStatus("scraping-message-hiperlibertad", f"Error en scraper al traer productos de {subCategory}")
            return []
