
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
from selenium.webdriver.chrome.service import Service
from flask import current_app
from api.sockets import notifyStatus

# from api.sockets import notifyStatus

_hTMLSession = HTMLSession()

class ScrapeDisco:
    activeDisco= True
    
    def scrape_disco_stop(self):
        self.activeDisco = False

    def save_to_mongodb(self, jsonData, category_name):
        """Save scraped data to MongoDB"""
        try:
            # Access lalistitadev database and productos collection
            mongodb_client = current_app.mongodb_client
            database = mongodb_client.lalistitadev
            collection = database.productos
            
            # Clear existing Disco data for this category
            collection.delete_many({"supermercado": "Disco", "categoria": category_name})
            
            # Add timestamp and category to each product
            for product in jsonData:
                product['scraped_at'] = datetime.utcnow()
                product['categoria'] = category_name
            
            # Insert all products in one operation
            if jsonData:
                collection.insert_many(jsonData)
                print(f"Saved {len(jsonData)} Disco products from {category_name} to MongoDB")
                notifyStatus("scraping-message-disco", f"Guardados {len(jsonData)} productos de {category_name} en base de datos")
                return True
                
        except Exception as e:
            print(f"Error saving Disco {category_name} data to MongoDB: {e}")
            notifyStatus("scraping-message-disco", f"Error al guardar {category_name} en base de datos")
            return False

    # este scrap carga todo con el boton Mostrar Mas, una vez cargados todos se procesan
    def scrape_disco(self, categoria):
        try:
            secciones_ = []
            page = 1

            # driver = webdriver.Chrome()
            
            service = Service('/usr/local/bin/chromedriver-141')
            options = webdriver.ChromeOptions()
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            # options.add_argument('--headless')  # Uncomment for background execution
            driver = webdriver.Chrome(service=service, options=options)

            driver.maximize_window()
            driver.implicitly_wait(50)

            # driver.get("https://www.disco.com.ar/almacen")
            # time.sleep(5)
            # seccionesReq = WebDriverWait(driver, 15).until(EC.visibility_of_all_elements_located(
            #     (By.CLASS_NAME, "vtex-search-result-3-x-filterContent")))

            # secciones = seccionesReq[0].find_elements(
            #     By.CLASS_NAME, "vtex-search-result-3-x-filterItem")

            # for seccion in secciones:
            #     href_ = seccion.get_attribute('title').split(".ar/")[1]
            #     secciones_.append(href_)
                
            secciones = [{"categoria": "almacen", "subcategorias": ["aceites-y-vinagres", "aceitunas-y-encurtidos", "aderezos",
                            "arroz-y-legumbres", "caldos-sopas-y-pure", "conservas",
                            "desayuno-y-merienda", "golosinas-y-chocolates", "sin-tacc", "panificados",
                            "para-preparar", "pastas-secas-y-salsas", "sal-pimienta-y-especias", "snacks"]}]


            # print("secciones " + str(secciones.__len__()))

            for seccion in secciones[0]["subcategorias"]:
                jsondata = []  # Reset jsondata for each subcategory
                notifyStatus("scraping-message-disco", f"Scrapeando subcategoría: {seccion}")
                
                # SCRAP DE SECCION
                driver.get("https://www.disco.com.ar/almacen/" + seccion)
                driver.execute_script(
                    "window.scrollTo(0, document.body.scrollHeight/2);")
                # driver.switch_to.window(driver.current_window_handle)
                time.sleep(5)

                # LEO EL TOTAL DE LA SECCION
                total = int(driver.find_element(
                    By.CLASS_NAME, "vtex-search-result-3-x-totalProducts--layout").text.split(" ")[0])
                
                if (total == 0):
                    print(f"No hay productos en {seccion}, continuando...")
                    continue

                print(f"Total de productos en {seccion}: {total}")
                
                # Scrapear todas las páginas de esta subcategoría
                for i in range(2, int((total/20))+1):
                    if not (self.activeDisco):
                        break

                    try:
                        notifyStatus("scraping-message-disco", f"{seccion} - página {i}")
                        print(f'scraping data from Disco - {seccion} pagina: {i}')
                        
                        url = 'https://www.disco.com.ar/almacen/' + seccion + '?page=' + str(i)
                        response = _hTMLSession.get(url)
                        response.html.arender(sleep=8)
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
                                        parsedNameUnidad = name_parse(jsonitemi["item"]["name"])
                                        jsonitea = {"supermercado": "Disco",
                                                    "name": parsedNameUnidad['name'], 
                                                    "unidad": parsedNameUnidad['unidad'], 
                                                    "brand": jsonitemi["item"]["brand"]["name"],
                                                    "sku": jsonitemi["item"]["sku"],
                                                    "price": jsonitemi["item"]["offers"]["lowPrice"]}
                                        if not any(element['name'] in jsonitea['name'] for element in jsondata):
                                            jsondata.append(jsonitea)
                                except Exception:
                                    print("Error parsing data from jsonItems")
                                    continue
                        else:
                            print(f"No se encontraron elementos en la página {i}")
                            continue

                    except Exception as ex:
                        print(f"Error al cargar la pagina {i}: {ex}")
                        notifyStatus("scraping-message-disco", f"Error al cargar la pagina: {i}")
                        continue

                # Guardar datos de esta subcategoría en MongoDB
                if jsondata:
                    jsondata.sort(key=lambda x: x["name"])
                    self.save_to_mongodb(jsondata, seccion)
                    print(f"Procesada subcategoría {seccion} con {len(jsondata)} productos")
                else:
                    print(f"No se obtuvieron productos para {seccion}")
                
                # También guardar el archivo JSON como backup (opcional)
                # fileName = seccion
                # with open('.disco/almacen/'+fileName+'.json', 'w') as outfile:
                #     json.dump(jsondata, outfile)

            # Close the driver
            try:
                driver.quit()
            except:
                pass

            notifyStatus("scraping-message-disco", "PROCESO TERMINADO - Todas las subcategorías procesadas")
            print("Proceso Disco terminado OK")

        except Exception as e:
            print(f"Error general en scraper Disco: {e}")
            # Close the driver in case of error
            try:
                driver.quit()
            except:
                pass

