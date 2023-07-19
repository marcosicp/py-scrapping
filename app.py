
from flask import Flask, render_template, request, redirect, url_for, jsonify
from flask_socketio import SocketIO, send, emit
from bs4 import BeautifulSoup
from requests_html import HTMLSession
from requests_html import AsyncHTMLSession
import os
import requests
import time
import asyncio
import json
import importlib.resources
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from flask_cors import CORS

asession = AsyncHTMLSession()
_hTMLSession = HTMLSession()
global activeCarre
activeCarre =True

global activeDisco
activeDisco =True

global activeHiperlibertad
activeHiperlibertad =True

global activeSupermami
activeSupermami =True

app = Flask(__name__,static_url_path='',)
CORS(app)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app)

cf_port = os.getenv("PORT")

title = "Flask and MongoDB"
heading = "Flask and MongoDB"


def redirect_url():
    return request.args.get('next') or \
        request.referrer or \
        url_for('index')


@app.route("/scrape")
def scrape():
    return render_template('scrape.html', todos=[])


@socketio.on('scraping-disco-stop')
def scrape_disco_stop():
    global activeDisco
    activeDisco = False
    
    # socketio.socketio. removeAllListeners("scraping-disco")

#este scrap carga todo con el boton Mostrar Mas, una vez cargados todos se procesan
@socketio.on('scraping-disco')
def scrape_disco():
    try:
        jsondata = []
        secciones_ = []
        page = 1
        
        driver = webdriver.Chrome()
        
        driver.maximize_window()
        driver.implicitly_wait(50)
        
        driver.get("https://www.disco.com.ar/almacen")
        time.sleep(5)
        seccionesReq = WebDriverWait(driver, 15).until(EC.visibility_of_all_elements_located((By.CLASS_NAME, "categoryList-container__items")))
        
        secciones = seccionesReq[0].find_elements(By.CLASS_NAME, "categoryItem")
        
        for seccion in secciones:
            href_ = seccion.get_attribute('href').split(".ar/")[1]
            secciones_.append(href_)
        
        print("secciones " + str(secciones.__len__()))
        
        for seccion in secciones_:
            ## SCRAP DE SECCION
            driver.get("https://www.disco.com.ar/" + seccion)
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight/2);")
            # driver.switch_to.window(driver.current_window_handle)
            time.sleep(5)
            
            # LEO EL TOTAL DE LA SECCION
            total = int(driver.find_element(By.CLASS_NAME, "vtex-search-result-3-x-totalProducts--layout").text.split(" ")[0])
            todos = WebDriverWait(driver, 15).until(EC.visibility_of_all_elements_located((By.ID, "gallery-layout-container")))
            results = todos[0].find_elements(By.XPATH, "*")
            emit("scraping-message-disco", str(page) + "-" + str(results.__len__()))
            if(results.__len__() == 0):
                return
            
            else:
                # for i in range(2, 10): #test
                for i in range(4, int((total/20))+1):
                    if not (activeDisco):
                        break
                    
                    try:
                        # driver.execute_script("window.scrollTo(0, document.body.scrollHeight/2);")
                        # buttonMas = WebDriverWait(driver, 15).until(EC.visibility_of_all_elements_located((By.XPATH, "//*[contains(text(), 'Mostrar más')]")))
                        
                        # time.sleep(3)
                        # buttonMas[0].click()
                        # time.sleep(3)
                        
                        emit("scraping-message-disco", page)
                        # page += 1
                        print('scraping data from Disco - ' + seccion +' pagina: ' + str(i))
                        url = 'https://www.disco.com.ar/' + seccion + '?page=' + \
                            str(page)  # -- set url
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
                                        jsonitea = {"supermercado": "Disco",
                                                    "name": jsonitemi["item"]["name"], "price": jsonitemi["item"]["offers"]["lowPrice"]}
                                        jsondata.append(jsonitea)
                                        attempt = 0
                                except Exception:
                                    print("Oops!  That was no valid number.  Try again...")
                                    continue
                        else:
                            # print('la pagina anterior debe ser reprocesada Disco - Almacen pagina: ' + str(page))
                            # page -= 1
                            # attempt+= 1
                            # time.sleep(15)
                            # if(attempt > 4):
                            #     flag=False
                            #     break
                            continue
                        emit("scraping-message-disco", str(i) + "-" + str(results.__len__()))
                    except Exception:
                        emit("scraping-message-disco", "Error al cargar la pagina:" + str(i))
                        continue
            
                # todos = WebDriverWait(driver, 15).until(EC.visibility_of_all_elements_located((By.ID, "gallery-layout-container")))
                # results = todos[0].find_elements(By.XPATH, "*")
                # for htmlItem in results:
                #     try:
                #         section =htmlItem.find_element(By.XPATH, "*")
                #         name =section.find_element(By.CLASS_NAME, "vtex-product-summary-2-x-nameContainer").text
                #         price =section.find_element(By.CLASS_NAME, "vtex-flex-layout-0-x-flexRow--mainRow-price-box").text
                #         jsonitea = {
                #             "supermercado": "Disco", "name": name,
                #             "price": price}
                #         jsondata.append(jsonitea)
                #     except Exception:
                #         print("Oops!  That was no valid number.  Try again...")

            jsondata.sort(key=lambda x: x["name"])
            fileName = seccion.split("/")[1]
            with open('.disco/almacen/'+fileName+'.json', 'w') as outfile:
                json.dump(jsondata, outfile)
                jsondata.clear()
        
        emit("scraping-message-disco", "PROCESO TERMINADO CON " + str(jsondata.__len__()) + " productos")
        print("Proceso Disco termino OK, con " + str(jsondata.__len__()) +  " productos")
        return render_template('index.html', todos=jsondata, carre=0, mami=0, hiper=0, disco=jsondata.__len__())
    except Exception:
        print("Oops!  That was no valid number.  Try again...")

@socketio.on('scraping-supermami-stop')
def scrape_supermami_stop():
    global activeSupermami
    activeSupermami = False
    
@socketio.on('scraping-mami')
def scrape_supermami():
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
            emit("scraping-message-mami", page)
            countPages = countPages+36
            print('scraping data from SuperMami pagina:' + str(page))
            url = 'https://www.supermami.com.ar/super/categoria/supermami-almacen/_/N-1tjm8rd?Nf=product.endDate%7CGTEQ+1.6723584E12%7C%7Cproduct.startDate%7CLTEQ+1.6723584E12&No=' + \
                str(countPages) + '&Nr=AND%28product.disponible%3ADisponible%2Cproduct.language%3Aespa%C3%B1ol%2Cproduct.priceListPair%3AsalePrices_listPrices%2COR%28product.siteId%3AsuperSite%29%29&Nrpp=36'  # -- set url
            response = _hTMLSession.get(url)
            response.html.arender(sleep=4)
            # -- get data and parse
            soup = BeautifulSoup(response.text, 'html.parser')

            productos = soup.find_all('div', class_='product')
            if(activeSupermami):
                if (len(productos) > 0):
                    for a in productos:
                        item = {
                            "supermercado": "SuperMami",
                            "name": a.find("div", {"class": "description limitRow tooltipHere"}).text, "price":  a.find(
                                "div", {"class": "precio-unidad"}).text.replace("$", "").replace("x un", "").replace("\t", "").replace("\r", "").replace("\n", "").replace("..", "")}
                        jsonData.append(item)  # -- append item to json
                else:
                    continue
            else: break

        jsonData.sort(key=lambda x: x["name"])
        with open('supermami.json', 'w') as outfile:
            # -- save jsondata to '.json' file
            json.dump(jsonData, outfile)
        emit("scraping-message-mami", "PROCESO TERMINADO CON " + str(jsonData.__len__()) + " productos")
        print("Proceso Mami termino OK, con " + str(jsonData.__len__()) +  " productos")
        return render_template('index.html', todos=jsonData, carre=0, mami=jsonData.__len__(), hiper=0, disco=0)

@socketio.on('scraping-carrefour-stop')
def scrape_carrefour_stop():
    global activeCarre
    activeCarre = False

# CON SELENIUM
@socketio.on('scraping-carrefour')
def scrape_carrefour():
    jsondata = []
    page = 1
    driver = webdriver.Chrome()
    driver.get("https://www.carrefour.com.ar/Almacen/")
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    driver.switch_to.window(driver.current_window_handle)
    time.sleep(10)
    delay = 5
  
    results = driver.find_elements(By.CLASS_NAME, "valtech-carrefourar-search-result-0-x-galleryItem")
    if(results.__len__() == 0):
        return
    
    else:
        emit("scraping-message-carrefour", str(page) + "-" + str(results.__len__()))
        total = int(driver.find_element(By.CLASS_NAME, "valtech-carrefourar-search-result-0-x-totalProducts--layout").text.split(" ")[0])
        
        # ya que le pego levanto los datos de la primera pegada
        for htmlItem in results:
            try:
                section =htmlItem.find_element(By.XPATH, "*")
                name =section.find_element(By.CLASS_NAME, "vtex-product-summary-2-x-productBrand").text
                price =section.find_element(By.CLASS_NAME, "vtex-flex-layout-0-x-flexColChild--wrapPrice").text
                # emit("scraping-message-carrefour", page)
                jsonitea = {
                    "supermercado": "Carrefour", "name": name,
                    "price": price}
                jsondata.append(jsonitea)
            except Exception:
                print("Oops!  That was no valid number.  Try again...")
        
        for i in range(2, int((total/16)-1)):
            if not (activeCarre):
                break
            
            url = 'https://www.carrefour.com.ar/Almacen/?page=' + \
                str(page)  # -- set url
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
                                        "name": jsonitemi["item"]["name"], "price": jsonitemi["item"]["offers"]["lowPrice"]}
                            jsondata.append(jsonitea)
                            attempt = 0
                    except Exception:
                        print("Oops!  That was no valid number.  Try again...")
                        continue
            # driver.get("https://www.carrefour.com.ar/Almacen/?page=" + str(i))
            # driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            # driver.switch_to.window(driver.current_window_handle)
            # time.sleep(10)
            # delay = 5
            
            # results = driver.find_elements(By.CLASS_NAME, "valtech-carrefourar-search-result-0-x-galleryItem")
            # if(results.__len__ == 0):
            #     break
            
            emit("scraping-message-carrefour", str(i) + "-" + str(results.__len__()))
            
            # for htmlItem in results:
            #     try:
            #         section =htmlItem.find_element(By.XPATH, "*")
            #         name =section.find_element(By.CLASS_NAME, "vtex-product-summary-2-x-productBrand").text
            #         price =section.find_element(By.CLASS_NAME, "vtex-flex-layout-0-x-flexColChild--wrapPrice").text
            #         jsonitea = {
            #             "supermercado": "Carrefour", "name": name,
            #             "price": price}
            #         jsondata.append(jsonitea)
            #     except Exception:
            #         print("Oops!  That was no valid number.  Try again...")
        
    emit("scraping-message-carrefour", "PROCESO TERMINADO CON " + str(jsondata.__len__()) + " productos")
    jsondata.sort(key=lambda x: x["name"])
    with open('carrefour.json', 'w') as outfile:
        json.dump(jsondata, outfile)
    return render_template('index.html', todos=jsondata, carre=jsondata.__len__(), mami=0, disco=0, hiper=0)

@socketio.on('scraping-hiperlibertad-stop')
def scrape_hiperlibertad_stop():
    global activeHiperlibertad
    activeHiperlibertad = False
    
@socketio.on('scraping-hiper')
def scrape_hiperlibertad():
    # EN ESTE SCRAP ES IMPOSIBLE SABER EL TOTAL, ASI QUE CON UN WHILE != [] SE SOLUCIONA PROVISORIAMENTE
    jsondata = []
    pageIncrement = 0
    flag = True
    attempt = 0

    while (flag & activeHiperlibertad):
        emit("scraping-message-hiper", pageIncrement)
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
    
    emit("scraping-message-hiper", "PROCESO TERMINADO CON " + str(jsondata.__len__()) + " productos")
    print("Proceso HiperLibertad termino OK, con " + str(jsondata.__len__()) +  " productos")
    return render_template('index.html', todos=jsondata,  carre=0, mami=0, hiper=jsondata.__len__(), disco=0)

@app.route('/')
def root():
    return render_template('index.html') # Return index.html 
    # return redirect("/supermercados")

@app.route("/supermercados")
def ReturnJSON():
    data4=[]
    for a in os.listdir(".disco/almacen"):
        # fileName=a+".json"
        with open(".disco/almacen/"+a) as file3:
            data4 = data4 + json.load(file3)
    with open('carrefour.json') as fp:
        data1 = json.load(fp)
        with open("supermami.json") as file1:
            data2 = json.load(file1)
            with open("hiperlibertad.json") as file2:
                data3 = json.load(file2)
                # with open("disco.json") as file3:
                #     data4 = json.load(file3)
                data = data1 + data2 + data3 + data4
                data.sort(key=lambda x: x["name"])

    ret = {'todos':data, 'carre':data1.__len__(), 'disco':data4.__len__(), 'mami':data2.__len__(), 'hiper':data3.__len__()}
    # return render_template('index.html', todos=data, carre=data1.__len__(), disco=data4.__len__(), mami=data2.__len__(), hiper=data3.__len__())
    return jsonify(ret)

@app.route("/supermercado-carrefour")
def supermercadosCarrefour():
    with open('carrefour.json') as fp:
        data = json.load(fp)
        data.sort(key=lambda x: x["name"])

    return render_template('index.html', todos=data, carre=data.__len__(), mami=0, hiper=0, disco=0
                           )


@app.route("/supermercado-disco")
def supermercadosDisco():
    with open('disco.json') as fp:
        data = json.load(fp)
        data.sort(key=lambda x: x["name"])

    return render_template('index.html', todos=data, carre=0, mami=0, hiper=0,disco=data.__len__()
                           )

@app.route("/supermercado-hiper")
def supermercadosHiper():
    with open('hiperlibertad.json') as fp:
        data = json.load(fp)
        data.sort(key=lambda x: x["name"])

    return render_template('index.html', todos=data, carre=0, mami=0, hiper= data.__len__(), disco=0)


@app.route("/supermercado-supermami")
def supermercadosSupermami():
    with open('supermami.json') as fp:
        data = json.load(fp)
        data.sort(key=lambda x: x["name"])

    return render_template('index.html', todos=data, carre=0, mami=data.__len__(), hiper= 0, disco=0)

if __name__ == '__main__':
    if cf_port is None:
        socketio.run(app, port=3000, debug=True)
    else:
        socketio.run(app, port=int(cf_port), debug=True)
