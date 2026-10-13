import test from 'node:test';
import assert from 'node:assert/strict';
import { adviceText } from '../renderer/views/resources.js';

test('trade advice text', () => {
  const names = { MAL: 'Malaya', ROM: 'Romania' };
  assert.equal(adviceText({ action: 'buy', buy: [{ seller: 'MAL', amount: 8, factories: 1 }], missing: 0 }, names),
    'Buy 8 from Malaya (1 factory)');
  assert.equal(adviceText({ action: 'cancel', cancel: [{ seller: 'ROM', amount: 16 }] }, names), 'Cancel 16 from Romania - not needed');
  assert.equal(adviceText({ action: 'short', missing: 3 }), '3 short - no seller or factories left');
  assert.equal(adviceText({ action: 'ok' }), 'OK');
});
