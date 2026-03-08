from threading import Thread
from flask import Blueprint, render_template, request, jsonify, url_for, Flask, current_app
import os
import json
import asyncio
from threading import Thread
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

@app_file2.route("/scraping-disco", methods=['POST'] )
def scrapingDisco():
    categoria = request.args.get('category')
    scrape_service = ScrapeDisco()
    Thread(target = scrape_service.scrape_disco(categoria),).start()
    
    return json.dumps({'success':True}), 200, {'ContentType':'application/json'} 
    
@app_file2.route("/scraping-hiperlibertad", methods=['POST'] )
def scrapingHiperlibertad():
    categoria = request.args.get('category')
    scrape_service = ScrapeHiperLibertad()
    scrape_service.scrape_hiperlibertad(categoria)
    
    return json.dumps({'success':True}), 200, {'ContentType':'application/json'} 
    
@app_file2.route("/scraping-supermami", methods=['POST'] )
def scrapingSupermami():
    categoria = request.args.get('category')
    scrape_service = ScrapeSuperMami()
    scrape_service.scrape_supermami(categoria)
    return json.dumps({'success':True}), 200, {'ContentType':'application/json'} 
    
@app_file2.route("/scraping-supermami-stop")
def scrapingSupermamiStop():
    scrape_service = ScrapeSuperMami()
    scrape_service.scrape_supermami_stop()
    
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

@app_file2.route("/supermercados")
def ReturnJSON():
    try:
        # Access MongoDB database and collection
        mongodb_client = current_app.mongodb_client
        database = mongodb_client.lalistitadev
        collection = database.productos
        
        # Get all products from the database
        all_products = list(collection.find({}, {"_id": 0}))  # Exclude MongoDB _id field
        
        # Organize products by supermarket
        disco = []
        carrefour = []
        hiperlibertad = []
        supermami = []
        
        for product in all_products:
            supermarket = product.get("supermercado", "").lower()
            if "disco" in supermarket:
                disco.append(product)
            elif "carrefour" in supermarket:
                carrefour.append(product)
            elif "hiperlibertad" in supermarket or "hiper" in supermarket:
                hiperlibertad.append(product)
            elif "supermami" in supermarket or "mami" in supermarket:
                supermami.append(product)
        
        # Remove duplicates by name for each supermarket
        disco = remove_duplicates_by_key(disco, 'name')
        carrefour = remove_duplicates_by_key(carrefour, 'name')
        hiperlibertad = remove_duplicates_by_key(hiperlibertad, 'name')
        supermami = remove_duplicates_by_key(supermami, 'name')
        
        # Combine all products and sort by name
        data = supermami + carrefour + hiperlibertad + disco
        data.sort(key=lambda x: x.get("name", ""))

        ret = {
            'todos': data, 
            'carre': len(carrefour), 
            'disco': len(disco),
            'mami': len(supermami), 
            'hiper': len(hiperlibertad)
        }
        
        return jsonify(ret)
        
    except Exception as e:
        print(f"Error reading from MongoDB: {e}")
        # Fallback to empty data if database fails
        return jsonify({
            'todos': [], 
            'carre': 0, 
            'disco': 0,
            'mami': 0, 
            'hiper': 0,
            'error': 'Database connection error'
        })


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

