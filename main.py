"""WSGI entry point.

    gunicorn main:app

This module exists because the Dockerfile has always targeted `main:app`
(`Dockerfile:36`) while no `main.py` existed: the image built and the container
died at startup (K-5). It also completes K-1/K-2, because a WSGI server imports
this module instead of running `python app.py`, so anything set up inside
`if __name__ == '__main__'` was never set up at all.

`app` is created at import time on purpose: WSGI servers expect a module-level
callable, and `create_app()` only assembles objects — `MongoClient` connects
lazily, so this import does not touch the network.
"""

from app import create_app

app = create_app()
