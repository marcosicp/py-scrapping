from bs4 import BeautifulSoup
from requests_html import HTMLSession
import json
import requests
import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

_hTMLSession = HTMLSession()

class ScrapeCarrefour:
    def scrape_carrefour_stop():
        global activeCarre
        activeCarre = False

    # CON SELENIUM



    def scrape_carrefour(param, socketio):
        jsondata = []

        # buscar secciones y subsecciones dinamicamente
        categorias = [{"categoria": "almacen", "subcategorias": ["aceites-y-vinagres", "arroz-y-legumbres", "caldos-sopas-y-pure",
                                                                "enlatados-y-conservas", "harinas", "pastas-secas", "reposteria-y-postres",
                                                                "sal-aderezos-y-saborizadores", "snacks"]},
                    {"categoria": "desayuno-y-merienda", "subcategorias": ["azucar-y-endulzantes", "budines-y-magdalenas", "cafe", "cereales-y-barritas",
                                                                            "galletitas-bizcochitos-y-tostadas", "golosinas-y-chocolates", "infusiones", "mermeladas-y-otros-dulces", "yerba"]}]

        driver = webdriver.Chrome()
        categoreq = next((x for x in categorias if x["categoria"] == param["categoria"]), None)

        if(categoreq is not None):
            socketio.emit("scraping-message-carrefour", "Scrapeando categoria: " + categoreq["categoria"] )
            for subcategoria in categoreq["subcategorias"]:
                try:
                    socketio.emit("scraping-message-carrefour", "Inicio Scrap sub-categoria: " + subcategoria)
                    driver.get("https://www.carrefour.com.ar/" +
                            categoreq["categoria"] + "/" + subcategoria)
                    driver.execute_script(
                        "window.scrollTo(0, document.body.scrollHeight);")
                    driver.switch_to.window(driver.current_window_handle)
                    time.sleep(10)
                    total = int(driver.find_element(
                        By.CLASS_NAME, "valtech-carrefourar-search-result-0-x-totalProducts--layout").text.split(" ")[0])
                    if (total == 0):
                        return

                    for i in range(1, int((total/16))):
                        if not (activeCarre):
                            break

                        url = 'https://www.carrefour.com.ar/' + categoreq["categoria"] + '/' + subcategoria + '?page=' + \
                            str(i)  # -- set url
                        response = _hTMLSession.get(url)
                        response.html.arender(sleep=8)
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
                                        jsonitea = {"supermercado": "Carrefour",
                                                    "name": jsonitemi["item"]["name"],
                                                    "brand": jsonitemi["item"]["brand"]["name"],
                                                    "sku": jsonitemi["item"]["sku"],
                                                    "price": jsonitemi["item"]["offers"]["lowPrice"]}
                                        if not any(element['name'] in jsonitea['name'] for element in jsondata):
                                            print('Chirp')
                                            jsondata.append(jsonitea)
                                        # attempt = 0
                                except Exception:
                                    socketio.emit("scraping-message-carrefour", "Error al construir array de subcategoria: " + subcategoria)
                                    print("Error al construir array")
                                    continue

                        socketio.emit("scraping-message-carrefour", str(i) + "-" + str(total))
                
                except Exception:
                    socketio.emit("scraping-message-carrefour", "Error en scraper al traer productos")
                    print("Error en scraper al traer productos")
                    continue
            fileName = categoreq["categoria"]
            with open('.carrefour/almacen/'+fileName+'.json', 'w') as outfile:
                json.dump(jsondata, outfile)
                jsondata.clear()
            return
            
        for categoria in categorias:
            socketio.emit("scraping-message-carrefour", "Scrapeando categoria: " + categoria["categorias"] )
            for subcategoria in categoria["subcategorias"]:
                try:
                    socketio.emit("scraping-message-carrefour", "Inicio Scrap sub-categoria: " + subcategoria)
                    driver.get("https://www.carrefour.com.ar/" +
                            categoria["categoria"] + "/" + subcategoria)
                    driver.execute_script(
                        "window.scrollTo(0, document.body.scrollHeight);")
                    driver.switch_to.window(driver.current_window_handle)
                    time.sleep(10)
                    total = int(driver.find_element(
                        By.CLASS_NAME, "valtech-carrefourar-search-result-0-x-totalProducts--layout").text.split(" ")[0])
                    if (total == 0):
                        return

                    for i in range(1, int((total/16))):
                        if not (activeCarre):
                            break

                        url = 'https://www.carrefour.com.ar/' + categoria["categoria"] + '/' + subcategoria + '?page=' + \
                            str(i)  # -- set url
                        response = _hTMLSession.get(url)
                        response.html.arender(sleep=8)
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
                                        jsonitea = {"supermercado": "Carrefour",
                                                    "name": jsonitemi["item"]["name"],
                                                    "brand": jsonitemi["item"]["brand"]["name"],
                                                    "sku": jsonitemi["item"]["sku"],
                                                    "price": jsonitemi["item"]["offers"]["lowPrice"]}
                                        if not any(element['name'] in jsonitea['name'] for element in jsondata):
                                            print('Chirp')
                                            jsondata.append(jsonitea)
                                        # attempt = 0
                                except Exception:
                                    socketio.emit("scraping-message-carrefour", "Error al construir array de subcategoria: " + subcategoria)
                                    print("Error al construir array")
                                    continue

                        socketio.emit("scraping-message-carrefour", str(i) + "-" + str(total))
                
                except Exception:
                    socketio.emit("scraping-message-carrefour", "Error en scraper al traer productos")
                    print("Error en scraper al traer productos")
                    continue
            fileName = categoria["categorias"]
            with open('.carrefour/almacen/'+fileName+'.json', 'w') as outfile:
                json.dump(jsondata, outfile)
                jsondata.clear()
            
        socketio.emit("scraping-message-carrefour", "PROCESO TERMINADO CON " +
            str(jsondata.__len__()) + " productos")
       