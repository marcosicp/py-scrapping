
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

from api.sockets import notifyStatus

# from api.sockets import notifyStatus

_hTMLSession = HTMLSession()


class ScrapeChangoMas:
    activeChangomas = True
    
    def scrape_changomas_stop(self):
        # global activeChangomas
        self.activeChangomas = False

    # este scrap carga todo con el boton Mostrar Mas, una vez cargados todos se procesan
    async def scrape_changomas(self, categoria):
        try:
            jsondata = []
            secciones_ = []
            page = 1

            driver = webdriver.Chrome()

            driver.maximize_window()
            driver.implicitly_wait(50)
            notifyStatus("scraping-message-changomas", "Inicio scrap")
            
            driver.get("https://www.masonline.com.ar/268?initialMap=productClusterIds&initialQuery=268&map=category-1,productclusternames&query=/desayuno-y-golosinas/mas-online---almacen")
            time.sleep(5)
            seccionesReq = WebDriverWait(driver, 15).until(EC.visibility_of_all_elements_located(
                (By.CLASS_NAME, "categoryList-container__items")))

            secciones = seccionesReq[0].find_elements(
                By.CLASS_NAME, "categoryItem")

            for seccion in secciones:
                href_ = seccion.get_attribute('href').split(".ar/")[1]
                secciones_.append(href_)

            print("secciones " + str(secciones.__len__()))

            for seccion in secciones_:
                # SCRAP DE SECCION
                driver.get("https://www.masonline.com.ar/268?initialMap=productClusterIds&initialQuery=268&map=category-1,productclusternames&query=/desayuno-y-golosinas/mas-online---almacen" + seccion)
                driver.execute_script(
                    "window.scrollTo(0, document.body.scrollHeight/2);")
                # driver.switch_to.window(driver.current_window_handle)
                time.sleep(5)

                # LEO EL TOTAL DE LA SECCION
                total = int(driver.find_element(
                    By.CLASS_NAME, "vtex-search-result-3-x-totalProducts--layout").text.split(" ")[0])
                todos = WebDriverWait(driver, 15).until(
                    EC.visibility_of_all_elements_located((By.ID, "gallery-layout-container")))
                results = todos[0].find_elements(By.XPATH, "*")
                # notifyStatus("scraping-message-changomas", str(page) +
                            #  "-" + str(results.__len__()))

                if (results.__len__() == 0):
                    return

                else:
                    # for i in range(2, 10): #test
                    for i in range(2, int((total/20))+1):
                        if not (self.activeChangomas):
                            break

                        try:
                            # driver.execute_script("window.scrollTo(0, document.body.scrollHeight/2);")
                            # buttonMas = WebDriverWait(driver, 15).until(EC.visibility_of_all_elements_located((By.XPATH, "//*[contains(text(), 'Mostrar más')]")))

                            # time.sleep(3)
                            # buttonMas[0].click()
                            # time.sleep(3)

                            # notifyStatus("scraping-message-changomas", i)
                            # page += 1
                            print('scraping data from ChangoMas - ' +
                                  seccion + ' pagina: ' + str(i))
                            url = 'https://www.masonline.com.ar/268?initialMap=productClusterIds&initialQuery=268&map=category-1,productclusternames&query=/desayuno-y-golosinas/mas-online---almacen/' + seccion + '?page=' + \
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
                                            jsonitea = {"supermercado": "ChangoMas",
                                                        "name": jsonitemi["item"]["name"], "price": jsonitemi["item"]["offers"]["lowPrice"]}
                                            if not any(element['name'] in jsonitea['name'] for element in jsondata):
                                                print('Chirp')
                                                jsondata.append(jsonitea)
                                            attempt = 0
                                    except Exception:
                                        print(
                                            "Oops!  That was no valid number.  Try again...")
                                        continue
                            else:
                                # print('la pagina anterior debe ser reprocesada changomas - Almacen pagina: ' + str(page))
                                # page -= 1
                                # attempt+= 1
                                # time.sleep(15)
                                # if(attempt > 4):
                                #     flag=False
                                #     break
                                continue
                            # # notifyStatus("scraping-message-changomas",
                            #              str(i) + "-" + str(results.__len__()))

                        except Exception:
                            # notifyStatus("scraping-message-changomas",
                            #              "Error al cargar la pagina:" + str(i))

                            continue

                jsondata.sort(key=lambda x: x["name"])
                fileName = seccion.split("/")[1]
                with open('.changomas/almacen/'+fileName+'.json', 'w') as outfile:
                    json.dump(jsondata, outfile)
                    jsondata.clear()

            notifyStatus("scraping-message-changomas", "PROCESO TERMINADO CON " +
                         str(jsondata.__len__()) + " productos")

            print("Proceso changomas termino OK, con " +
                  str(jsondata.__len__()) + " productos")

        except Exception:
            print("Oops!  That was no valid number.  Try again...")
        finally:
            driver.close()
            # return
            
        # pass
