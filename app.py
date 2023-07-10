
from flask import Flask, render_template, request, redirect, url_for
from flask_socketio import SocketIO, send, emit
from bs4 import BeautifulSoup
from requests_html import HTMLSession
from requests_html import AsyncHTMLSession
import os
import requests
import time
import asyncio
import json
# import importlib.resources

asession = AsyncHTMLSession()
s = HTMLSession()
global activeCarre
activeCarre =True

global activeDisco
activeDisco =True

global activeHiperlibertad
activeHiperlibertad =True

global activeSupermami
activeSupermami =True

app = Flask(__name__)
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

@socketio.on('scraping-disco')
def scrape_disco():
    jsondata = []
    page = 1
    attempt = 0
    flag = True
    url = 'https://www.disco.com.ar/almacen?map=category-1&page=1'  # -- set url
    response = s.get(url)
    response.html.arender(sleep=8)
    soup = BeautifulSoup(response.text, 'html.parser')  # -- get data and parse
    print('scraping data from Disco - Almacen')
    anchors = soup.find_all('div', class_='flex flex-column min-vh-100 w-100')
    if (len(anchors) > 0):
        item = anchors[0].next.contents[0]
        jsonitem = json.loads(item)
        for jsonitemi in jsonitem["itemListElement"]:
            try:
                if ("name" in jsonitemi["item"]):
                    jsonitea = {
                        "supermercado": "Disco", "name": jsonitemi["item"]["name"],
                        "price": jsonitemi["item"]["offers"]["lowPrice"]}
                    jsondata.append(jsonitea)
            except Exception:
                print("Oops!  That was no valid number.  Try again...")

        while (flag & activeDisco):
            emit("scraping-message-disco", page)
            page += 1
            print('scraping data from Disco - Almacén pagina: ' + str(page))
            url = 'https://www.disco.com.ar/almacen?map=category-1&page=' + \
                str(page)  # -- set url
            response = s.get(url)
            response.html.arender(sleep=8)
            # -- get data and parse
            soup = BeautifulSoup(response.text, 'html.parser')

            anchors = soup.find_all(
                'div', class_='flex flex-column min-vh-100 w-100')
            if (len(anchors) > 0):
                if (anchors[0].next.name == 'img'):
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

    jsondata.sort(key=lambda x: x["name"])
    with open('disco.json', 'w') as outfile:
        json.dump(jsondata, outfile)
    return render_template('index.html', todos=jsondata, carre=0, mami=0, hiper=0, disco=jsondata.__len__())

@socketio.on('scraping-supermami-stop')
def scrape_supermami_stop():
    global activeSupermami
    activeSupermami = False
    
@socketio.on('scraping-mami')
def scrape_supermami():
    jsonData = []
    url = 'https://www.supermami.com.ar/super/categoria/supermami-almacen/_/N-1tjm8rd?Nf=product.endDate%7CGTEQ+1.6723584E12%7C%7Cproduct.startDate%7CLTEQ+1.6723584E12&No=36'  # -- set url
    response = s.get(url)
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
            response = s.get(url)
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

        return render_template('index.html', todos=jsonData, carre=0, mami=jsonData.__len__(), hiper=0, disco=0)

@socketio.on('scraping-carrefour-stop')
def scrape_carrefour_stop():
    global activeCarre
    activeCarre = False
    
@socketio.on('scraping-carrefour')
def scrape_carrefour():
    jsondata = []
    page = 1
    attempt = 0
    flag = True
    url = 'https://www.carrefour.com.ar/Almacen/'  # -- set url
    response = s.get(url)
    response.html.arender(sleep=8)
    soup = BeautifulSoup(response.text, 'html.parser')  # -- get data and parse
    print('scraping data from Carrefour - Almacen')
    anchors = soup.find_all('div', class_='flex flex-column min-vh-100 w-100')
    if (len(anchors) > 0):
        item = anchors[0].next.contents[0]
        jsonitem = json.loads(item)
        for jsonitemi in jsonitem["itemListElement"]:
            try:
                if ("name" in jsonitemi["item"]):
                    jsonitea = {
                        "supermercado": "Carrefour", "name": jsonitemi["item"]["name"],
                        "price": jsonitemi["item"]["offers"]["lowPrice"]}
                    jsondata.append(jsonitea)
            except Exception:
                print("Oops!  That was no valid number.  Try again...")

        while (flag & activeCarre):
            page += 1
            emit("scraping-message-carrefour", page)
            print('scraping data from Carrefour - Almacén pagina: ' + str(page))
            url = 'https://www.carrefour.com.ar/Almacen/?page=' + \
                str(page)  # -- set url
            response = s.get(url)
            time.sleep(8)
            response.html.arender(sleep=8)
            # -- get data and parse
            soup = BeautifulSoup(response.text, 'html.parser')

            anchors = soup.find_all(
                'div', class_='flex flex-column min-vh-100 w-100')
            if (len(anchors) > 0):
                # if (anchors[0].next.contents[0].name == 'button'):
                #     flag = False
                #     break
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
            else:
                print(
                    'la pagina anterior debe ser reprocesada Carrefour - Almacen pagina: ' + str(page))
                page -= 1
                attempt += 1
                time.sleep(15)
                if (attempt > 4):
                    flag = False
                    break
                continue

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
        return render_template('index.html', todos=jsondata,  carre=0, mami=0, hiper=jsondata.__len__(), disco=0)

@app.route('/')
def redirected():
    return redirect("/supermercados")

@app.route("/supermercados")
def supermercados():
    with open('carrefour.json') as fp:
        data1 = json.load(fp)
        with open("supermami.json") as file1:
            data2 = json.load(file1)
            with open("hiperlibertad.json") as file2:
                data3 = json.load(file2)
                with open("disco.json") as file3:
                    data4 = json.load(file3)
                    data = data1 + data2 + data3 + data4
                    data.sort(key=lambda x: x["name"])

    return render_template('index.html', todos=data, carre=data1.__len__(), disco=data4.__len__(), mami=data2.__len__(), hiper=data3.__len__())


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
