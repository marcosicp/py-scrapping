# LaListita - Comparador de Precios de Supermercados 🛒

Sistema de scraping y comparación de precios de productos de supermercados argentinos. Combina un backend **Flask** con scrapers **Selenium** y un frontend **Angular** con monitoreo en tiempo real vía **SocketIO**.

## Supermercados soportados

| Supermercado | Método de scraping |
|---|---|
| Disco | Selenium |
| Carrefour | Selenium |
| ChangoMás | Selenium (async + paginación) |
| HiperLibertad | API directa |
| SuperMami | Selenium |

## Arquitectura

```
Angular Frontend (adminpro/)
        │
        ▼
Flask Backend (app.py, puerto 3000)
   ├── REST API (api/routes.py)
   ├── SocketIO (api/sockets.py) ← actualizaciones en tiempo real
   └── Scrapers (api/scrapers/)
        │
        ▼
   MongoDB Cloud ("lalistita")
```

## Tech Stack

- **Backend:** Python 3.11, Flask 3.0, Flask-SocketIO, Gunicorn
- **Scrapers:** Selenium 4.15, BeautifulSoup4, Requests
- **Base de datos:** MongoDB Atlas (PyMongo)
- **Frontend:** Angular 16, Angular Material, Tailwind CSS
- **Deploy:** Docker, Google Cloud Run

## Requisitos previos

- Python 3.10+
- Node.js y npm (para el frontend Angular)
- Google Chrome (versión compatible con ChromeDriver)
- ChromeDriver instalado manualmente en `/usr/local/bin/chromedriver-141`
- Acceso a una instancia MongoDB (local o Atlas)

## Instalación

### 1. Clonar el repositorio

```bash
git clone <repo-url>
cd preciosflaskpy
```

### 2. Configurar el backend

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Variables de entorno

Crear un archivo `.env` en la raíz del proyecto:

```env
MONGODB_URI=mongodb+srv://<usuario>:<password>@cluster0.mongodb.net/lalistita?retryWrites=true&w=majority
FLASK_ENV=development
PORT=3000
```

### 4. Construir el frontend

```bash
cd adminpro
npm install
ng build --base-href /static/
cd ..
```

Los archivos compilados se generan en `static/` y Flask los sirve automáticamente.

## Uso

### Desarrollo local

```bash
source .venv/bin/activate
python app.py
```

- **App principal:** http://localhost:3000
- **Panel de scraping:** http://localhost:3000/scrape
- **API de productos:** http://localhost:3000/supermercados

### Producción (Docker)

```bash
docker build -t preciosflask .
docker run -p 3000:3000 --env-file .env preciosflask
```

## API Endpoints

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/` | Frontend principal (Angular) |
| `GET` | `/scrape` | Panel de monitoreo de scrapers |
| `GET` | `/supermercados` | Todos los productos (JSON) |
| `POST` | `/scraping-disco?category=X` | Iniciar scraper Disco |
| `POST` | `/scraping-carrefour?category=X` | Iniciar scraper Carrefour |
| `POST` | `/scraping-changomas?category=X` | Iniciar scraper ChangoMás |
| `POST` | `/scraping-hiperlibertad?category=X` | Iniciar scraper HiperLibertad |
| `POST` | `/scraping-supermami?category=X` | Iniciar scraper SuperMami |
| `GET` | `/scraping-changomas-stop` | Detener scraper ChangoMás |
| `GET` | `/scraping-supermami-stop` | Detener scraper SuperMami |

## Estructura del proyecto

```
preciosflaskpy/
├── app.py                    # Entry point Flask
├── requirements.txt          # Dependencias Python
├── Dockerfile                # Configuración Docker
├── gunicorn_config.py        # Config servidor producción
├── .env                      # Variables de entorno (no versionado)
├── api/
│   ├── routes.py             # Endpoints REST
│   ├── sockets.py            # Configuración SocketIO
│   ├── helpers.py            # Utilidades
│   ├── models/
│   │   └── productos.py      # Modelo de productos
│   └── scrapers/
│       ├── scrap_disco.py
│       ├── scrap_carrefour.py
│       ├── scrap_changomas.py
│       ├── scrap_hiperlibertad.py
│       └── scrap_supermami.py
├── adminpro/                 # Frontend Angular 16
│   └── src/app/
├── static/                   # Build de Angular (servido por Flask)
└── templates/
    ├── index.html            # Template principal
    └── scrape.html           # Monitor de scrapers (SocketIO)
```

## ChromeDriver

> **Importante:** `webdriver-manager` puede fallar en macOS. Se recomienda la instalación manual.

```bash
# Verificar versión de Chrome
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --version

# Descargar el ChromeDriver correspondiente y colocarlo en:
/usr/local/bin/chromedriver-141
```

Los scrapers están configurados para usar esta ruta explícita:

```python
driver = webdriver.Chrome(service=ChromeService("/usr/local/bin/chromedriver-141"))
```

## Comunicación en tiempo real

Los scrapers reportan progreso al frontend mediante SocketIO:

```python
from api.sockets import notifyStatus
notifyStatus("scraping-message-disco", "Scrapeando página 3 de 10...")
```

El panel en `/scrape` muestra las actualizaciones en vivo para cada supermercado.