# LaListita — Comparador de precios de supermercados 🛒

Comparador de precios de supermercados argentinos. Scrapers en Python extraen
catálogos de cinco cadenas, los persisten en MongoDB, una API Flask los agrupa
por producto canónico y un dashboard Angular 21 los muestra.

> **La fuente de verdad es [`AGENTS.md`](AGENTS.md).** Este README es la puerta
> de entrada; el detalle vive en [`docs/agent-context/`](docs/agent-context/)
> ([repo-map](docs/agent-context/repo-map.md),
> [runbook](docs/agent-context/runbook.md),
> [known-issues](docs/agent-context/known-issues.md),
> [deploy-render](docs/agent-context/deploy-render.md)).
> Si una instrucción de acá falla, este archivo está mal: corregilo.

## Supermercados soportados

| Supermercado | Slug | Método |
|---|---|---|
| Disco | `disco` | API de catálogo VTEX |
| Carrefour | `carrefour` | API de catálogo VTEX |
| ChangoMás | `changomas` | API de catálogo VTEX |
| La Anónima | `laanonima` | HTTP + JSON-LD |
| SuperMami | `supermami` | HTTP + Oracle Endeca |

Cada cadena es un módulo en `api/scrapers/` y una línea en
`default_registry()`. Rutas, panel de monitoreo y CLI se generan desde el
registry.

## Arquitectura

```
Navegador
   │
   ▼
Flask (app.py / main.py, puerto 3000)
   ├── api/blueprints/     ── SPA, panel /scrape, API REST, aliases legacy
   ├── api/services/       ── agrupación canónica, orquestación de runs
   ├── api/repositories/   ── puerto + adaptador Mongo
   ├── api/scrapers/       ── BaseScraper + una implementación por cadena
   └── api/sockets.py      ── progreso en vivo (SocketIO, modo threading)
        │                              ▲
        ▼                              │
   MongoDB · lalistitadev.productos    │
                                       │
Angular 21 (adminpro/src) ── build ──► static/ ── servido por Flask
```

## Stack

| Capa | Versión |
|---|---|
| Python (todos los targets) | **3.15.2** (`.python-version`, `runtime.txt`, `Dockerfile`) |
| Flask / flask-socketio / flask-cors | 3.1.3 · 5.7.2 · 6.0.5 |
| Driver Mongo | pymongo 4.19.0 (directo, sin ODM) |
| Scraping | selenium 4.52.0, beautifulsoup4 4.15.0, lxml 6.1.3 |
| Servidor | gunicorn 26.2.0 |
| Frontend | **Angular 21.2** (NgModule), Material 21.x, ag-grid, TypeScript 5.9 |
| Base de datos | MongoDB (por defecto `lalistitadev`) |
| Deploy | **Render, `runtime: docker`** (`render.yaml`) |

## Requisitos previos

- **Python 3.15** (3.11 es el piso de pymongo, pero el proyecto fija 3.15.2).
- Node.js y npm, para el bundle de Angular.
- Google Chrome o Chromium, sólo si vas a correr scrapers.
- Acceso a una instancia MongoDB (local o Atlas).

**No hace falta instalar ChromeDriver a mano.** `api/scrapers/browser.py` es la
única fuente del driver y usa Selenium Manager, que resuelve el binario que
coincide con tu Chrome. Sólo en un host raro se fija con `CHROMEDRIVER_PATH`.

## Puesta en marcha

```bash
# 1. Backend
python3.15 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Frontend — static/ es build output y NO está versionado
cd adminpro && npm ci && npm run build && cd ..
```

Sin el paso 2, `/` responde **503** con el comando exacto a ejecutar. Es a
propósito: un clone limpio no trae bundle.

```bash
# 3. Correr
python app.py                  # http://localhost:3000  (y /scrape)

# Backend + dev server de Angular juntos; Ctrl+C frena los dos
./dev.sh                       # Flask :3000, Angular :4200
```

## Variables de entorno

`.env` en la raíz (gitignoreado; también lo excluye `.dockerignore`).

| Variable | Default | Para qué |
|---|---|---|
| `SECRET_KEY` | `secret!` | **Ponela siempre.** El default es una constante pública y firma tus sesiones. |
| `MONGODB_URI` | `mongodb://localhost:27017/` | Conexión. Necesaria para Atlas. |
| `MONGODB_DB` | `lalistitadev` | Base de datos. |
| `MONGODB_TLS_CA_FILE` | — | CA privada. Sin ella, un URI TLS usa el bundle de `certifi`. |
| `CHROMEDRIVER_PATH` | — | Fija el binario del driver. Sin ella, Selenium Manager. |
| `CHROME_BINARY` | — | Fija el binario del navegador (p. ej. `/usr/bin/chromium`). |
| `CHROME_HEADLESS` | `0` | `1/true/yes/on` para correr sin ventana. |
| `PORT` | `3000` (dev) · `10000` (imagen) | Puerto de escucha. |

```env
SECRET_KEY=<una cadena larga y aleatoria>
MONGODB_URI=mongodb+srv://<usuario>:<password>@cluster0.mongodb.net/?retryWrites=true&w=majority
MONGODB_DB=lalistitadev
```

## API

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/` | Dashboard Angular (503 si falta el bundle) |
| `GET` | `/scrape` | Panel de control de scrapers |
| `GET` | `/supermercados` | Catálogo plano (formato legacy) |
| `GET` | `/api/productos/agrupados` | **Filas canónicas** — lo que consume el dashboard |
| `GET` | `/api/scrapers` | Estado de las cinco cadenas |
| `GET` | `/api/scrapers/<slug>` | Estado de una cadena |
| `POST` | `/api/scrapers/<slug>/start` | Arranca (`?category=` o body JSON) → 202 |
| `POST` | `/api/scrapers/<slug>/stop` | Frena → 202 |

Los aliases viejos siguen vivos, generados desde el registry:
`POST /scraping-<slug>?category=X` y `GET|POST /scraping-<slug>-stop`.
Preferí `/api/scrapers` para código nuevo.

## Uso sin Flask

```bash
python -m api.cli list                          # cadenas registradas
python -m api.cli run carrefour --category almacen
```

## Tests

```bash
pip install -r requirements-dev.txt
pytest                                          # sin red, sin Chrome, sin DB real
```

Las únicas excepciones son las integraciones de Mongo, que corren sólo si
definís `MONGODB_TEST_URI` y lo hacen sobre una base descartable.

El frontend **no tiene specs**. El único chequeo browser-free es:

```bash
cd adminpro && npm run verify:selection
```

El scraping en vivo se verifica a mano: necesita Chrome, driver y base real.

## Deploy

Render con `runtime: docker` (`render.yaml`). El `Dockerfile` construye el
bundle de Angular en un stage de Node y lo copia al runtime de Python. La
runtime nativa de Python **no sirve**: no instala 3.15 y no construye el
frontend.

```bash
# Réplica local, tal como corre en el contenedor
docker build -t lalistita .
docker run -p 3000:10000 --env-file .env lalistita
```

El contenedor escucha en `10000` (`PORT` por defecto en la imagen), no en 3000.
El proceso queda en `--workers 1`: el estado de los runs y los clientes de
SocketIO viven en memoria.

## Dos cosas que muerden

1. **`replace_products` reemplaza, no appendea.** Cada scrape sustituye la
   rebanada `supermercado`/`categoria` completa (inserta lo nuevo, poda lo
   viejo; un scrape vacío no hace nada). No lo corras contra datos que te
   importen sin pensarlo.
2. **`static/` no está versionado** y nunca se edita a mano. La fuente es
   `adminpro/src/`.

El resto del inventario de trampas está en [`AGENTS.md`](AGENTS.md) §7.
