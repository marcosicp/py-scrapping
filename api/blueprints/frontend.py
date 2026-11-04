"""Frontend blueprint: the SPA root and the scrape monitor page.

The SPA root moved verbatim from ``api/routes.py`` in T3. Since T13 the
``/scrape`` monitor page is generated from the scraper registry instead
of carrying five hand-written cards.
"""

import os

from flask import Blueprint, current_app, render_template, send_from_directory

from api.container import get_services

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
    manager = get_services().scrapers
    scrapers = [{"slug": cls.slug, "label": cls.label,
                 "categories": list(cls.categories)}
                for cls in manager.registry.classes()]
    return render_template('scrape.html', scrapers=scrapers, todos=[])
