from threading import Thread
from flask import Blueprint, request, url_for, send_from_directory
import os
import json
import asyncio
from api.scrapers.scrap_carrefour import ScrapeCarrefour
from api.scrapers.scrap_changomas import ScrapeChangoMas

app_file2 = Blueprint('app_file2',__name__)
# def configure_routes(app: Flask):
def redirect_url():
    return request.args.get('next') or \
        request.referrer or \
        url_for('index')

@app_file2.route("/scraping-carrefour", methods=['POST'] )
def scrapingCarrefour():
    categoria = request.args.get('category')
    scrape_service = ScrapeCarrefour()
    Thread(target=scrape_service.scrape_carrefour, args=(categoria,)).start()
    return json.dumps({'success':True}), 200, {'ContentType':'application/json'} 
    
@app_file2.route("/scraping-changomas", methods=['POST'])
def scrapingChangomas():
    categoria = request.args.get('category')
    scrape_service = ScrapeChangoMas()
    
    # Función para ejecutar la función asíncrona en un hilo separado
    def run_async_scraper():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(scrape_service.scrape_changomas(categoria))
        finally:
            loop.close()
    
    # Ejecutar en un hilo separado
    Thread(target=run_async_scraper).start()
    
    return json.dumps({'success':True}), 200, {'ContentType':'application/json'} 
    
@app_file2.route("/scraping-changomas-stop")
def scrapingChangomasStop():
    scrape_service = ScrapeChangoMas()
    scrape_service.scrape_changomas_stop()

@app_file2.route("/supermercado-carrefour")
def supermercadosCarrefour():
    with open('carrefour.json') as fp:
        data = json.load(fp)
        data.sort(key=lambda x: x["name"])

    return send_from_directory(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static'), 'index.html')


@app_file2.route("/supermercado-disco")
def supermercadosDisco():
    with open('disco.json') as fp:
        data = json.load(fp)
        data.sort(key=lambda x: x["name"])

    return send_from_directory(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static'), 'index.html')


@app_file2.route("/supermercado-hiper")
def supermercadosHiper():
    with open('hiperlibertad.json') as fp:
        data = json.load(fp)
        data.sort(key=lambda x: x["name"])

    return send_from_directory(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static'), 'index.html')


@app_file2.route("/supermercado-supermami")
def supermercadosSupermami():
    with open('supermami.json') as fp:
        data = json.load(fp)
        data.sort(key=lambda x: x["name"])

    return send_from_directory(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static'), 'index.html')

