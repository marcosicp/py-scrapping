
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

class ScrapeHiperLibertad:
    def scrape_hiperlibertad_stop(socketio):
        global activeHiperlibertad
        activeHiperlibertad = False



    def scrape_hiperlibertad(categoria, socketio):
        # EN ESTE SCRAP ES IMPOSIBLE SABER EL TOTAL, ASI QUE CON UN WHILE != [] SE SOLUCIONA PROVISORIAMENTE
        jsondata = []
        pageIncrement = 0
        flag = True
        attempt = 0

        while (flag & activeHiperlibertad):
            socketio.emit("scraping-message-hiper", pageIncrement)
            url = 'https://www.hiperlibertad.com.ar/api/catalog_system/pub/products/search/almacen?O=OrderByPriceASC&_from=' + \
                str(pageIncrement) + '&_to=' + \
                str(pageIncrement+49) + '&ft&sc=1'  # -- set url
            response = requests.get(url)
            jsonitem = json.loads(response.text)
            if (len(jsonitem) > 0):
                for jsonite in jsonitem:
                    jsonitea = {"supermercado": "Hiperlibertad", "name": jsonite["productName"], "price": jsonite["items"]
                                [0]["sellers"][0]["commertialOffer"]["Price"]}
                    jsondata.append(jsonitea)
                pageIncrement += 49
                attempt = 0
            else:
                attempt += 1
                if (attempt > 4):
                    flag = False
                    break
                continue

        jsondata.sort(key=lambda x: x["name"])
        with open('hiperlibertad.json', 'w') as outfile:
            json.dump(jsondata, outfile)

        socketio.emit("scraping-message-hiper", "PROCESO TERMINADO CON " +
            str(jsondata.__len__()) + " productos")
        print("Proceso HiperLibertad termino OK, con " +
            str(jsondata.__len__()) + " productos")
        # return render_template('index.html', todos=jsondata,  carre=0, mami=0, hiper=jsondata.__len__(), disco=0)
