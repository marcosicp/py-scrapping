/**
 * Browser-free test for the chain-list selection and totals (D-16).
 *
 * AGENTS.md §8 forbids browser-based checks in this repository, and karma
 * needs Chrome, so the pure logic lives in `selection.ts` and is exercised
 * here through Node's built-in TypeScript type stripping:
 *
 *     npm run verify:selection
 *
 * This is the in-repo replacement for the /tmp harness that left the manual
 * round as the only evidence for this module (advisory `R3-SELECTION-TEST`).
 */

import * as selection from '../src/app/pages/dashboard/selection.ts';

const failures = [];
let checks = 0;

function check(name, condition, detail) {
  checks += 1;
  if (!condition) {
    failures.push(detail ? `${name} — ${detail}` : name);
  }
}

function equal(name, actual, expected) {
  check(name, Object.is(actual, expected), `expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
}

// -- exports exist: a missing one is a wiring failure, not a silent pass
for (const name of ['toggleOffer', 'chainTotal', 'formatAmount']) {
  equal(`exports ${name}()`, typeof selection[name], 'function');
}

const { toggleOffer, chainTotal, formatAmount } = selection;

if (typeof toggleOffer === 'function') {
  // -- the two Cañuelas presentations of the owner's report share one display
  // name per chain; each canonical row must reach the list with its size
  const oil900 = { name: 'ACEITE DE GIRASOL CAÑUELAS X .', price: 3269.0 };
  const oil1500 = { name: 'ACEITE DE GIRASOL CAÑUELAS X .', price: 5299.0 };

  let list = toggleOffer('row-900', oil900, '900 cc', true, undefined);
  list = toggleOffer('row-1500', oil1500, '1.5 lts', true, list);

  equal('two presentations reach the list', list.length, 2);
  equal('first entry keeps its row id', list[0].id, 'row-900');
  equal('first entry carries its presentation', list[0].presentation, '900 cc');
  equal('second entry carries its presentation', list[1].presentation, '1.5 lts');
  equal('second entry keeps its own price', list[1].price, 5299.0);

  // -- a second click on the same row does not duplicate its entry
  equal('re-adding the same row is a no-op', toggleOffer('row-900', oil900, '900 cc', true, list).length, 2);

  // -- deselecting one row removes exactly that row, never its siblings
  const afterRemove = toggleOffer('row-900', oil900, '900 cc', false, list);
  equal('deselect keeps the sibling', afterRemove.length, 1);
  equal('deselect keeps the sibling presentation', afterRemove[0].presentation, '1.5 lts');

  // -- the list is undefined before the first selection
  check('toggle tolerates an undefined list', Array.isArray(toggleOffer('r', oil900, '', false, undefined)));
}

if (typeof chainTotal === 'function') {
  const list = [
    { id: 'a', name: 'A', presentation: '900 cc', price: 4399.0 },
    { id: 'b', name: 'B', presentation: '1.5 lts', price: 6985.0 },
  ];
  equal('total sums the list', chainTotal(list), 11384.0);
  equal('total of an empty list is zero', chainTotal([]), 0);
  equal('total tolerates an undefined list', chainTotal(undefined), 0);
  // -- legacy documents can carry a string price; a null one must not poison it
  equal('total coerces a string price', chainTotal([
    { id: 'c', name: 'C', presentation: '', price: '1290' },
  ]), 1290);
  equal('total ignores an unusable price', chainTotal([
    { id: 'd', name: 'D', presentation: '', price: null },
    { id: 'e', name: 'E', presentation: '', price: 100 },
  ]), 100);
}

if (typeof formatAmount === 'function') {
  // -- es-AR money rendering, not a raw float
  equal('formats with the local separators', formatAmount(11384.6), '$11.384,60');
  equal('formats zero', formatAmount(0), '$0,00');
}

if (failures.length > 0) {
  console.error(`selection logic FAILED (${failures.length} of ${checks} checks)`);
  for (const failure of failures) {
    console.error(`  - ${failure}`);
  }
  process.exit(1);
}

console.log(`selection logic OK (${checks} checks)`);
