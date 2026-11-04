"""Frontend blueprint: the SPA root and the scrape monitor page.

Moved verbatim from ``api/routes.py`` in T3; responses are unchanged.
"""

import os

from flask import Blueprint, current_app, render_template, send_from_directory

frontend = Blueprint("frontend", __name__)


@frontend.route('/')
def root():
    # static/ is not versioned; it is Angular build output. Without this guard a
    # fresh clone answers a bare 404 and the cause is invisible.
    if not os.path.exists(os.path.join(current_app.static_folder, 'index.html')):
        return (
            'Frontend bundle missing: static/ is not versioned.\n'
            'Build it with:\n'
            '  cd adminpro && npm ci && npm run build\n',
            503,
            {'Content-Type': 'text/plain; charset=utf-8'},
        )
    return send_from_directory(current_app.static_folder, 'index.html')


@frontend.route("/scrape")
def scrape():
    return render_template('scrape.html', todos=[])
