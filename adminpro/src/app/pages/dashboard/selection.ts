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
  /**
   * Presentation of the canonical row (`data.unidad`), never the chain's own
   * name: SuperMami stores every Cañuelas presentation as
   * "ACEITE DE GIRASOL CAÑUELAS X .", size included nowhere (D-14).
   */
  presentation: string;
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
 * @param presentation canonical row presentation (`data.unidad`), see D-14
 * @param selected the row's new selection state
 * @param items current list, possibly undefined before the first selection
 */
export function toggleOffer(
  rowId: string,
  offer: ChainOffer,
  presentation: string,
  selected: boolean,
  items: ChainEntry[] | undefined
): ChainEntry[] {
  const list = items ?? [];
  if (selected) {
    // -- one entry per canonical row: a second presentation is a second row
    return list.some((item) => item.id === rowId)
      ? list
      : list.concat([{
          id: rowId,
          name: offer.name,
          presentation: presentation ?? '',
          price: offer.price,
        }]);
  }
  return list.filter((item) => item.id !== rowId);
}

/** Price of one entry as a number; an unusable legacy price counts as zero. */
function numericPrice(price: number | string | null): number {
  const value = typeof price === 'number' ? price : Number(price);
  return Number.isFinite(value) ? value : 0;
}

/**
 * Total of one chain list, computed from the entries the grid shows (D-15).
 *
 * This is the single source of truth for the amount rendered under each list:
 * the component used to push the same number into the grid through
 * `setPinnedBottomRowData`, a second route nobody could verify without a
 * browser.
 */
export function chainTotal(items: ChainEntry[] | undefined): number {
  return (items ?? []).reduce((total, item) => total + numericPrice(item.price), 0);
}

/** Render an amount as Argentine pesos (`$11.384,60`). */
export function formatAmount(value: number): string {
  return '$' + new Intl.NumberFormat('es-AR', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Number.isFinite(value) ? value : 0);
}
