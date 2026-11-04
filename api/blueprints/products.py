"""Products blueprint: the `/supermercados` API the dashboard consumes.

HTTP shell only: the grouping/dedupe logic lives in ``api.services.products``
and the data in the ``ProductRepository``. The legacy ``try/except`` boundary
stays here so a failing database still answers HTTP 200 with the empty
fallback the Angular client already handles (D7).
"""

from flask import Blueprint, current_app, jsonify

from api.container import get_services

products = Blueprint("products", __name__)


@products.route("/supermercados")
def supermercados():
    try:
        return jsonify(get_services().products.catalog())
    except Exception:
        current_app.logger.exception("Error building the product catalog")
        # Fallback to empty data if database fails
        return jsonify({
            'todos': [],
            'carre': 0,
            'disco': 0,
            'mami': 0,
            'hiper': 0,
            'error': 'Database connection error'
        })
