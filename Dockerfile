# Stage 1 — build the Angular bundle.
# static/ is no longer committed, so the image produces it here.
FROM node:24-alpine AS frontend

WORKDIR /build

# Copy only the manifests first so `npm ci` is cached independently of the source.
COPY adminpro/package.json adminpro/package-lock.json ./
RUN npm ci

COPY adminpro/ ./
# angular.json sets outputPath to ../static, i.e. /static from /build.
RUN npm run build


# Stage 2 — Python runtime.
# https://hub.docker.com/_/python
FROM python:3.15-slim

# Allow statements and log messages to immediately appear in the Knative logs
ENV PYTHONUNBUFFERED True

ENV APP_HOME /app
WORKDIR $APP_HOME

# Dependencies first: this layer only invalidates when requirements.txt changes.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Chromium for the scrapers. Without CHROME_BINARY the driver guesses the
# browser binary heuristically (Selenium Manager probes candidate paths,
# chromedriver falls back to well-known names) and a guess that misses this
# image fails the session, so the browser is pinned to Debian's
# /usr/bin/chromium through the CHROME_BINARY setting
# (api/scrapers/browser.py). This is what makes
# `POST /api/scrapers/<slug>/start` work in the container. It is gated by a
# build arg: `--build-arg INSTALL_CHROMIUM=0` produces a lean image for a
# deploy that does not scrape.
ARG INSTALL_CHROMIUM=1
RUN if [ "$INSTALL_CHROMIUM" = "1" ]; then \
        DEBIAN_FRONTEND=noninteractive apt-get update && \
        DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
            chromium chromium-driver fonts-liberation ca-certificates && \
            rm -rf /var/lib/apt/lists/* ; \
    fi

# Render injects PORT, but a local `docker run` does not — a default keeps
# `--bind :$PORT` from expanding to an empty port.
ENV PORT=10000
EXPOSE 10000

COPY . ./
# Bring in the bundle built by the frontend stage.
COPY --from=frontend /static ./static

# `main.py` exists and exposes `main:app` — the same entry point
# `gunicorn main:app` runs locally. The process model must stay
# `--workers 1 --threads 8`: ScraperManager keeps scrape-run state in-process
# and SocketIO runs in `threading` async mode, so extra workers would fork
# both the run state and the realtime clients.
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 main:app
