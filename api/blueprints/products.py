"""Products blueprint: the `/supermercados` API the dashboard consumes.

HTTP shell only: the grouping/dedupe logic lives in ``api.services.products``
and the data in the ``ProductRepository``. The legacy ``try/except`` boundary
stays here so a failing database still answers HTTP 200 with the empty
fallback the Angular client already handles (D7). A repository outage keeps
the legacy ``Database connection error`` label AND the legacy
``Error reading from MongoDB`` log signal that alerting relies on (R3-002);
any other defect answers a distinct error value and never logs a database
failure.
"""

from flask import Blueprint, current_app, jsonify

from api.container import get_services
from api.repositories import RepositoryUnavailable

products = Blueprint("products", __name__)

# Fallback payload the Angular client already handles; ``error`` carries
# what failed.
_DATABASE_ERROR = "Database connection error"
_UNEXPECTED_ERROR = "Internal server error"


@products.route("/supermercados")
def supermercados():
    try:
        return jsonify(get_services().products.catalog())
    except RepositoryUnavailable:
        current_app.logger.exception("Error reading from MongoDB")
        # Fallback to empty data if database fails
        return jsonify({
            'todos': [],
            'carre': 0,
            'disco': 0,
            'mami': 0,
            'hiper': 0,
            'error': _DATABASE_ERROR,
        })
    except Exception:
        # A non-database defect inside the payload: not an outage, so it
        # must not be labelled 'Database connection error' nor log one.
        current_app.logger.exception(
            "Unexpected error building the product catalog")
        return jsonify({
            'todos': [],
            'carre': 0,
            'disco': 0,
            'mami': 0,
            'hiper': 0,
            'error': _UNEXPECTED_ERROR,
        })


@products.route("/api/productos/agrupados")
def productos_agrupados():
    try:
        return jsonify(get_services().products.grouped_catalog())
    except RepositoryUnavailable:
        current_app.logger.exception("Error reading from MongoDB")
        # Fallback to empty data if database fails
        return jsonify({
            'productos': [],
            'carre': 0,
            'disco': 0,
            'mami': 0,
            'hiper': 0,
            'error': _DATABASE_ERROR,
        })
    except Exception:
        # A non-database defect inside the payload: not an outage, so it
        # must not be labelled 'Database connection error' nor log one.
        current_app.logger.exception(
            "Unexpected error building the grouped product catalog")
        return jsonify({
            'productos': [],
            'carre': 0,
            'disco': 0,
            'mami': 0,
            'hiper': 0,
            'error': _UNEXPECTED_ERROR,
        })
