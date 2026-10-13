import test from 'node:test';
import assert from 'node:assert/strict';
import { energyText, factoryLines } from '../renderer/views/factories.js';

test('factory lines like the game tooltip (GER 1941)', () => {
  assert.deepEqual(factoryLines({ total: 268, owned: 208, occupation: 61, subjects: 2, trade: 0, damaged: 3 }).map(([l, v]) => [l, v]),
    [['Owned', 208], ['From occupation', 61], ['Subject Relations', 2], ['Damaged', -3]]);
  assert.deepEqual(factoryLines({ total: 2, owned: 9, occupation: 0, subjects: -7, trade: 0, damaged: 0 }).map(([l, v]) => [l, v]),
    [['Owned', 9], ['Subject Relations', -7]]);   // a subject giving factories to its overlord
  assert.equal(energyText({ demand: 4091.628, coverage: 0.97126 }), '4091.6 (97.1%)');
});
