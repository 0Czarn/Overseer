import test from 'node:test';
import assert from 'node:assert/strict';
import { shares } from '../renderer/views/resources.js';

test('supply shares: kept at home, to market, imported', () => {
  // SOV 1936 rubber: produced 2, 1 to market, 8 imported
  assert.deepEqual(shares({ produced: 2, to_market: 1, imported: 8 }), { home: 1, market: 1, imported: 8, total: 10 });
  assert.equal(shares({ produced: 0, to_market: 0, imported: 0 }).total, 0);
});
