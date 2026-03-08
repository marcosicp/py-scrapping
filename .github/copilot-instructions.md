# AI Coding Agent Instructions: Precios Flask Price Scraping System

## System Overview

This is a **hybrid Flask/Angular application** for scraping grocery prices from multiple Argentine supermarket chains. The system combines a Python Flask backend with Selenium web scrapers and an Angular frontend for real-time monitoring.

### Core Architecture

```
Flask Backend (Python 3.11) → MongoDB Cloud → Angular Frontend
     ↓
Selenium Scrapers (5 supermarkets) → Real-time SocketIO updates
```

## Project Structure & Components

### Backend (Flask)
- **Entry Point**: `app.py` - Main Flask application with Blueprint registration
- **API Routes**: `api/routes.py` - REST endpoints for scraper control and data retrieval
- **Real-time Communication**: `api/sockets.py` - SocketIO configuration for progress updates
- **Database**: MongoDB cloud instance ("lalistita" database)
- **Port**: 3000 (configured for local development)

### Scrapers (`api/scrapers/`)
Each scraper is a separate class with consistent patterns:
- **Disco**: `scrap_disco.py` - Selenium-based scraper
- **Carrefour**: `scrap_carrefour.py` - Selenium-based scraper  
- **ChangoMás**: `scrap_changomas.py` - Async Selenium scraper with pagination
- **HiperLibertad**: `scrap_hiperlibertad.py` - API-based scraper
- **SuperMami**: `scrap_supermami.py` - Selenium-based scraper

### Frontend (Angular)
- **Location**: `adminpro/` folder
- **Build Process**: `ng build` with specific base-href configuration
- **Integration**: Static files served by Flask from `static/` directory
- **Templates**: Flask templates in `templates/` (scrape.html for monitoring)

## Critical Technical Details

### ChromeDriver Management
**IMPORTANT**: Manual ChromeDriver management is required due to webdriver-manager reliability issues on macOS:

```python
# Current working configuration (ChromeDriver 141)
driver = webdriver.Chrome(service=ChromeService("/usr/local/bin/chromedriver-141"))
```

- **ChromeDriver Path**: `/usr/local/bin/chromedriver-141`
- **Chrome Version**: 141.x (must match ChromeDriver version)
- **Issue**: webdriver-manager auto-installation often fails
- **Solution**: Manual installation and explicit path specification

### Environment Setup

#### Virtual Environment
```bash
python3 -m venv .venv
source .venv/bin/activate  # macOS/Linux
pip install -r requirements.txt
```

#### Environment Variables (.env)
```
MONGODB_URI=mongodb+srv://[credentials]@cluster0.mongodb.net/lalistita?retryWrites=true&w=majority
FLASK_ENV=development
PORT=3000
```

#### Database Connection
- **MongoDB Cloud**: Atlas cluster with "lalistita" database
- **Connection**: Automatic initialization in `app.py`
- **Collections**: Product data organized by supermarket

### Build & Deployment Process

#### Development Workflow
1. **Install Dependencies**: `pip install -r requirements.txt`
2. **Environment Setup**: Configure `.env` file
3. **Angular Build**: `cd adminpro && ng build --base-href /static/`
4. **Run Flask**: `python app.py` (serves on port 3000)

#### Production Deployment
- **Docker**: Dockerfile with Gunicorn WSGI server
- **Config**: `gunicorn_config.py` for production settings
- **Static Files**: Angular build output in `static/` directory

## Scraper Architecture Patterns

### Common Scraper Structure
```python
class ScrapeXYZ:
    def __init__(self):
        self.active = True  # Control flag for stopping
    
    def scrape_xyz_stop(self):
        self.active = False
    
    def scrape_xyz(self, categoria):
        driver = webdriver.Chrome(service=ChromeService("/usr/local/bin/chromedriver-141"))
        # Scraping logic with real-time updates
        notifyStatus("scraping-message-xyz", progress_message)
```

### Real-time Progress Updates
All scrapers use SocketIO for live progress reporting:
```python
from api.sockets import notifyStatus
notifyStatus("scraping-message-{supermarket}", "Progress update")
```

### Threading & Concurrency
- **API Routes**: Use threading for non-blocking scraper execution
- **State Management**: Class-level flags for start/stop control
- **Error Handling**: Graceful fallbacks with driver cleanup

## Development Guidelines

### When Modifying Scrapers
1. **Always test ChromeDriver compatibility** - verify correct driver path
2. **Maintain consistent progress reporting** - use `notifyStatus()` pattern
3. **Implement proper cleanup** - ensure `driver.close()` in finally blocks
4. **Handle dynamic content** - use WebDriverWait for element loading

### When Updating Dependencies
1. **Selenium**: Test with current ChromeDriver version
2. **Flask/SocketIO**: Verify real-time communication still works
3. **Angular**: Re-run build process and update static files

### Database Operations
- **Connection**: Auto-handled by Flask app initialization
- **Collections**: Organized by supermarket (disco, carrefour, changomas, etc.)
- **Data Format**: Standardized product JSON structure

### Frontend Integration
- **Static Serving**: Flask serves Angular build from `static/`
- **API Calls**: Frontend communicates via REST endpoints in `api/routes.py`
- **Real-time Updates**: SocketIO client in templates for progress monitoring

## Common Issues & Solutions

### ChromeDriver Problems
**Symptom**: "session not created" errors
**Solution**: Verify ChromeDriver version matches Chrome browser
```bash
# Check Chrome version
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --version

# Use matching ChromeDriver version
driver = webdriver.Chrome(service=ChromeService("/usr/local/bin/chromedriver-[version]"))
```

### Virtual Environment Issues
**Symptom**: Module import errors
**Solution**: Ensure virtual environment is activated and dependencies installed
```bash
source .venv/bin/activate
pip install -r requirements.txt
```

### MongoDB Connection Issues
**Symptom**: Database connection timeouts
**Solution**: Verify `.env` file configuration and network connectivity

### Angular Build Issues
**Symptom**: Static files not updating
**Solution**: Re-run Angular build with correct base-href
```bash
cd adminpro
ng build --base-href /static/
```

## Testing & Debugging

### Local Testing
1. **Start Flask**: `python app.py`
2. **Open Browser**: `http://localhost:3000`
3. **Monitor Logs**: Terminal output shows scraper progress
4. **Real-time UI**: `http://localhost:3000/scrape` for monitoring interface

### Production Testing
1. **Docker Build**: `docker build -t preciosflask .`
2. **Container Run**: `docker run -p 3000:3000 preciosflask`
3. **Health Check**: Verify endpoints respond correctly

## Key Files & Their Purposes

| File | Purpose | Notes |
|------|---------|-------|
| `app.py` | Flask application entry point | Blueprint registration, MongoDB init |
| `api/routes.py` | REST API endpoints | Scraper control, data aggregation |
| `api/sockets.py` | SocketIO configuration | Real-time progress updates |
| `api/scrapers/*.py` | Individual scrapers | Selenium/API-based data collection |
| `requirements.txt` | Python dependencies | Unified dependency management |
| `.env` | Environment configuration | MongoDB URI, Flask settings |
| `adminpro/` | Angular frontend | Build with `ng build --base-href /static/` |
| `static/` | Served static files | Angular build output |
| `templates/scrape.html` | Monitoring interface | Real-time scraper progress |
| `Dockerfile` | Container configuration | Production deployment |

## Quick Start Commands

```bash
# Setup
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Build Frontend
cd adminpro && ng build --base-href /static/ && cd ..

# Run Development Server
python app.py

# Access Application
open http://localhost:3000
```

Remember: This system requires careful ChromeDriver version management and proper environment configuration for reliable operation.