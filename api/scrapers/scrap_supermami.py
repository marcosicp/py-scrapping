
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

class ScrapeSuperMami:
    # @socketio.on('scraping-supermami-stop')
    def scrape_supermami_stop(socketio):
        global activeSupermami
        activeSupermami = False


    # @socketio.on('scraping-mami')
    def scrape_supermami(socketio):
        jsonData = []
        url = 'https://www.supermami.com.ar/super/categoria/supermami-almacen/_/N-1tjm8rd?Nf=product.endDate%7CGTEQ+1.6723584E12%7C%7Cproduct.startDate%7CLTEQ+1.6723584E12&No=36'  # -- set url
        response = _hTMLSession.get(url)
        response.html.arender(sleep=4)
        soup = BeautifulSoup(response.text, 'html.parser')  # -- get data and parse
        total = int(soup.find_all('p', class_='txt-result')
                    [0].findAll("strong")[2].text)
        print('Total de paginas SuperMami :' + str(total))
        productos = soup.find_all('div', class_='product')
        if (len(productos) > 0):
            print('scraping data from SuperMami')
            for a in productos:
                item = {"supermercado": "SuperMami", "name": a.find("div", {"class": "description limitRow tooltipHere"}).text, "price":  a.find(
                    "div", {"class": "precio-unidad"}).text.replace("$", "").replace("x un", "").replace("\t", "").replace("\r", "").replace("\n", "").replace("..", "")}
                jsonData.append(item)  # -- append item to json

            totalPages = round(total/36)
            countPages = 0
            for page in range(1, totalPages):
                socketio.emit("scraping-message-mami", page)
                countPages = countPages+36
                print('scraping data from SuperMami pagina:' + str(page))
                url = 'https://www.supermami.com.ar/super/categoria/supermami-almacen/_/N-1tjm8rd?Nf=product.endDate%7CGTEQ+1.6723584E12%7C%7Cproduct.startDate%7CLTEQ+1.6723584E12&No=' + \
                    str(countPages) + '&Nr=AND%28product.disponible%3ADisponible%2Cproduct.language%3Aespa%C3%B1ol%2Cproduct.priceListPair%3AsalePrices_listPrices%2COR%28product.siteId%3AsuperSite%29%29&Nrpp=36'  # -- set url
                response = _hTMLSession.get(url)
                response.html.arender(sleep=4)
                # -- get data and parse
                soup = BeautifulSoup(response.text, 'html.parser')

                productos = soup.find_all('div', class_='product')
                if (activeSupermami):
                    if (len(productos) > 0):
                        for a in productos:
                            item = {
                                "supermercado": "SuperMami",
                                "name": a.find("div", {"class": "description limitRow tooltipHere"}).text, "price":  a.find(
                                    "div", {"class": "precio-unidad"}).text.replace("$", "").replace("x un", "").replace("\t", "").replace("\r", "").replace("\n", "").replace("..", "")}
                            jsonData.append(item)  # -- append item to json
                    else:
                        continue
                else:
                    break

            jsonData.sort(key=lambda x: x["name"])
            with open('supermami.json', 'w') as outfile:
                # -- save jsondata to '.json' file
                json.dump(jsonData, outfile)
            socketio.emit("scraping-message-mami", "PROCESO TERMINADO CON " +
                str(jsonData.__len__()) + " productos")
            print("Proceso Mami termino OK, con " +
                str(jsonData.__len__()) + " productos")
            # return render_template('index.html', todos=jsonData, carre=0, mami=jsonData.__len__(), hiper=0, disco=0)

