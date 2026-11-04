from flask import Blueprint, request, url_for, send_from_directory
import os
import json

app_file2 = Blueprint('app_file2',__name__)
# def configure_routes(app: Flask):
def redirect_url():
    return request.args.get('next') or \
        request.referrer or \
        url_for('index')

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
