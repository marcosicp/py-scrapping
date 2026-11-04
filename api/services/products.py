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

        for product in self._repository.find_all():
            supermarket = product.get("supermercado", "").lower()
            if "disco" in supermarket:
                disco.append(product)
            elif "carrefour" in supermarket:
                carrefour.append(product)
            elif "hiperlibertad" in supermarket or "hiper" in supermarket:
                hiperlibertad.append(product)
            elif "supermami" in supermarket or "mami" in supermarket:
                supermami.append(product)

        # Remove duplicates by name for each supermarket
        disco = remove_duplicates_by_key(disco, 'name')
        carrefour = remove_duplicates_by_key(carrefour, 'name')
        hiperlibertad = remove_duplicates_by_key(hiperlibertad, 'name')
        supermami = remove_duplicates_by_key(supermami, 'name')

        # Combine all products and sort by name
        data = supermami + carrefour + hiperlibertad + disco
        data.sort(key=lambda x: x.get("name", ""))

        return {
            'todos': data,
            'carre': len(carrefour),
            'disco': len(disco),
            'mami': len(supermami),
            'hiper': len(hiperlibertad),
        }
