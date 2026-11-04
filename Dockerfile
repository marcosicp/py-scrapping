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

COPY . ./
# Bring in the bundle built by the frontend stage.
COPY --from=frontend /static ./static

# NOTE: this CMD still targets a module that does not exist (there is no main.py).
# Known issue K-5 — fixing it requires the WSGI application factory from K-1/K-2.
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 main:app
