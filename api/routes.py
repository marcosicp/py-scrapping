# from api.helpers.py.helpers import remove_duplicates_by_key
# from helpers import remove_duplicates_by_key
from threading import Thread
from flask import Blueprint, render_template, request, jsonify, url_for, Flask
# from .scrapers import scrape_disco, scrape_supermami, scrape_carrefour, scrape_hiperlibertad, remove_duplicates_by_key
# from .models import MyObject
import os
import json

from api.helpers import remove_duplicates_by_key
from api.scrapers.scrap_carrefour import ScrapeCarrefour
from api.scrapers.scrap_changomas import ScrapeChangoMas
from api.scrapers.scrap_disco import ScrapeDisco
from api.scrapers.scrap_hiperlibertad import ScrapeHiperLibertad
from api.scrapers.scrap_supermami import ScrapeSuperMami

app_file2 = Blueprint('app_file2',__name__)
# def configure_routes(app: Flask):
def redirect_url():
    return request.args.get('next') or \
        request.referrer or \
        url_for('index')

@app_file2.route('/')
def root():
    return render_template('index.html')  # Return index.html
# return redirect("/supermercados")

@app_file2.route("/scrape")
def scrape():
    return render_template('scrape.html', todos=[])

@app_file2.route("/scraping-disco")
def scrapingDisco(categoria):
    scrape_service = ScrapeDisco()
    scrape_service.scrape_disco(categoria)
    
@app_file2.route("/scraping-hiperlibertad")
def scrapingHiperlibertad(categoria):
    scrape_service = ScrapeHiperLibertad()
    scrape_service.scrape_hiperlibertad(categoria)
    
@app_file2.route("/scraping-supermami")
def scrapingSupermami(categoria):
    scrape_service = ScrapeSuperMami()
    scrape_service.scrape_supermami(categoria)
    
@app_file2.route("/scraping-carrefour")
def scrapingCarrefour(categoria):
    scrape_service = ScrapeCarrefour()
    scrape_service.scrape_carrefour(categoria)
    
@app_file2.route("/scraping-changomas", methods=['POST'])
def scrapingChangomas():
    categoria = request.args.get('category')
    scrape_service = ScrapeChangoMas()
    scrape_service.scrape_changomas(categoria)
    # pass
    # thread = Thread(target=do_work, kwargs={'value': request.args.get('value', 20)})
    # thread.start()
    
    return json.dumps({'success':True}), 200, {'ContentType':'application/json'} 
    
@app_file2.route("/scraping-changomas-stop")
def scrapingChangomasStop():
    scrape_service = ScrapeChangoMas()
    scrape_service.scrape_changomas_stop()

@app_file2.route("/supermercados")
def ReturnJSON():
    data4 = []
    for a in os.listdir(".disco/almacen"):
        with open(".disco/almacen/"+a) as file3:
            data4 = data4 + json.load(file3)
    new_objects_list = remove_duplicates_by_key(data4, 'name')
    data4 = new_objects_list
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

    ret = {'todos': data, 'carre': data1.__len__(), 'disco': data4.__len__(
    ), 'mami': data2.__len__(), 'hiper': data3.__len__()}
    # return render_template('index.html', todos=data, carre=data1.__len__(), disco=data4.__len__(), mami=data2.__len__(), hiper=data3.__len__())
    return jsonify(ret)


@app_file2.route("/supermercado-carrefour")
def supermercadosCarrefour():
    with open('carrefour.json') as fp:
        data = json.load(fp)
        data.sort(key=lambda x: x["name"])

    return render_template('index.html', todos=data, carre=data.__len__(), mami=0, hiper=0, disco=0
                        )


@app_file2.route("/supermercado-disco")
def supermercadosDisco():
    with open('disco.json') as fp:
        data = json.load(fp)
        data.sort(key=lambda x: x["name"])

    return render_template('index.html', todos=data, carre=0, mami=0, hiper=0, disco=data.__len__()
                        )


@app_file2.route("/supermercado-hiper")
def supermercadosHiper():
    with open('hiperlibertad.json') as fp:
        data = json.load(fp)
        data.sort(key=lambda x: x["name"])

    return render_template('index.html', todos=data, carre=0, mami=0, hiper=data.__len__(), disco=0)


@app_file2.route("/supermercado-supermami")
def supermercadosSupermami():
    with open('supermami.json') as fp:
        data = json.load(fp)
        data.sort(key=lambda x: x["name"])

    return render_template('index.html', todos=data, carre=0, mami=data.__len__(), hiper=0, disco=0)

