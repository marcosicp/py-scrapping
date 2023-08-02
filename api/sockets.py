import time
# from api.scrapers.scrap.disco import ScrapeDisco
# from api.scrapers.scrap.disco import ScrapeDisco
from flask_socketio import SocketIO, send, emit
# from selenium.webdriver.support.ui import WebDriverWait
from requests_html import HTMLSession
# from requests_html import AsyncHTMLSession
import json
import requests

from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup

# from api.scrapers.scrap_disco import ScrapeDisco

_hTMLSession = HTMLSession()
socketio = SocketIO()


# @socketio.on('scraping-disco-stop')
# def scrape_disco_stop():
#     scrape_service = ScrapeDisco()
#     scrape_service.scrape_disco_stop()



    # return


# @socketio.on('scraping-supermami-stop')
# def scrape_supermami_stop():
#     global activeSupermami
#     activeSupermami = False


# @socketio.on('scraping-carrefour-stop')
# def scrape_carrefour_stop():
#     global activeCarre
#     activeCarre = False


# @socketio.on('scraping-hiperlibertad-stop')
# def scrape_hiperlibertad_stop():
#     global activeHiperlibertad
#     activeHiperlibertad = False
def notifyStatus(paramText, paramValue):
    socketio.emit(paramText, paramValue)

def configure_sockets(app):
    socketio.init_app(app)
    
    # def notifyStatus(paramText, paramValue):
    #     emit(paramText, paramValue)
