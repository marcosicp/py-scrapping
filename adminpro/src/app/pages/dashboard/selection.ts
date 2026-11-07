/**
 * Chain-list selection for the grouped master grid (D-10).
 *
 * The master grid emits one canonical row per product with one offer per
 * chain; selecting a row copies each present offer into that chain's list.
 * A chain can reach two different rows through the same display name
 * (SuperMami stores every Cañuelas presentation as "ACEITE DE GIRASOL
 * CAÑUELAS X ."), so the entry identity is the canonical row id, never the
 * offer name: keyed by name a second presentation is silently dropped on add
 * and one deselect removes every sibling entry.
 *
 * Angular-free on purpose: the toggle is verifiable without a browser
 * (AGENTS.md §8), so it does not need karma/Chrome to be exercised.
 */

/** One line of a per-chain list. */
export interface ChainEntry {
  /** Canonical row id — the entry identity. */
  id: string;
  /** Chain-local display name of the offer. */
  name: string;
  /** Chain-local price; legacy documents can carry a string. */
  price: number | string | null;
}

/** The per-chain part of a canonical row's `offers[chain]`. */
export interface ChainOffer {
  name: string;
  price: number | string | null;
}

/**
 * Add or remove one canonical row's offer in a chain list.
 *
 * @param rowId canonical row id (`data.id` in the master grid)
 * @param offer that chain's offer (`data.offers[chain]`)
 * @param selected the row's new selection state
 * @param items current list, possibly undefined before the first selection
 */
export function toggleOffer(
  rowId: string,
  offer: ChainOffer,
  selected: boolean,
  items: ChainEntry[] | undefined
): ChainEntry[] {
  const list = items ?? [];
  if (selected) {
    // -- one entry per canonical row: a second presentation is a second row
    return list.some((item) => item.id === rowId)
      ? list
      : list.concat([{ id: rowId, name: offer.name, price: offer.price }]);
  }
  return list.filter((item) => item.id !== rowId);
}
