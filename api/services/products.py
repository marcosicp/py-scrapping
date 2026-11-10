"""Product catalog service.

Faithful port of the legacy ``/supermercados`` handler in ``api/routes.py``
(moved out in T3): group by supermarket, deduplicate by name, concatenate,
sort and count. The payload must stay byte-compatible with what the Angular
dashboard already consumes (D7).

The service performs no error handling: repository exceptions (and a missing
``name`` key inside a grouped document) propagate untouched — the blueprint
owns the legacy fallback response.
"""

from __future__ import annotations

from typing import Any

from api.helpers import remove_duplicates_by_key
from api.repositories.products import ProductRepository
from api.services import matching


class ProductService:
    """Read-side logic for the product catalog."""

    def __init__(self, repository: ProductRepository) -> None:
        self._repository = repository

    def catalog(self) -> dict[str, Any]:
        # -- append item to each supermarket group by substring, first match wins
        disco = []
        carrefour = []
        hiperlibertad = []
        supermami = []
        changomas = []

        for product in self._repository.find_all():
            supermarket = product.get("supermercado", "").lower()
            if "disco" in supermarket:
                disco.append(product)
            elif "carrefour" in supermarket:
                carrefour.append(product)
            # -- the ``hiper`` bucket keeps its payload key (the Angular
            # dashboard reads ``items!.hiper``) and now carries La Anónima,
            # the chain that replaced HiperLibertad: documents stored under
            # either name land here.
            elif ("hiperlibertad" in supermarket or "hiper" in supermarket
                  or "anónima" in supermarket or "anonima" in supermarket):
                hiperlibertad.append(product)
            elif "supermami" in supermarket or "mami" in supermarket:
                supermami.append(product)
            # -- no existing key is a substring of "changomas", so this
            # branch cannot shadow the ones above
            elif "changomas" in supermarket or "changomás" in supermarket:
                changomas.append(product)

        # Remove duplicates by name for each supermarket
        disco = remove_duplicates_by_key(disco, 'name')
        carrefour = remove_duplicates_by_key(carrefour, 'name')
        hiperlibertad = remove_duplicates_by_key(hiperlibertad, 'name')
        supermami = remove_duplicates_by_key(supermami, 'name')
        changomas = remove_duplicates_by_key(changomas, 'name')

        # -- concatenation order is the tie-break contract for same-name
        # products across supermarkets (supermami, carrefour, hiperlibertad,
        # disco, changomas) and is pinned by
        # tests/test_products_api.py::test_stable_tie_break_across_supermarkets
        data = supermami + carrefour + hiperlibertad + disco + changomas
        data.sort(key=lambda x: x.get("name", ""))

        return {
            'todos': data,
            'carre': len(carrefour),
            'disco': len(disco),
            'mami': len(supermami),
            'hiper': len(hiperlibertad),
            'chang': len(changomas),
        }

    def grouped_catalog(self) -> dict[str, Any]:
        """Grouped catalog for ``/api/productos/agrupados`` (D-6).

        Reads every document through the same repository port ``catalog``
        uses and delegates the grouping to the matching service (T2), whose
        §3 payload includes one row per canonical product plus one consumed-
        document count per chain bucket.
        """
        return matching.group_products(self._repository.find_all())
