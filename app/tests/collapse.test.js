import test from 'node:test';
import assert from 'node:assert/strict';
import { tileName } from '../renderer/lib/collapse.js';
import { diffTone } from '../renderer/views/compare.js';

test('a tile keeps its name when numbers or the country in its title change', () => {
  assert.equal(tileName('Tree german_focus - 210 focuses (0 completed, 6 available)'), tileName('Tree german_focus - 199 focuses (3 completed, 2 available)'));
  assert.equal(tileName('Live stockpile of SOV (game memory)'), tileName('Live stockpile of GER (game memory)'));
  assert.notEqual(tileName('Army'), tileName('Air Force'));
});

test('arrows: more / less, green when better for the stat', () => {
  assert.deepEqual(diffTone('soft_attack', 12, 10), { arrow: '▲', tone: 'good' });
  assert.deepEqual(diffTone('soft_attack', 8, 10), { arrow: '▼', tone: 'bad' });
  assert.deepEqual(diffTone('build_cost_ic', 8, 10), { arrow: '▼', tone: 'good' });
  assert.deepEqual(diffTone('supply_consumption', 1.2, 1), { arrow: '▲', tone: 'bad' });
  assert.deepEqual(diffTone('combat_width', 20, 18), { arrow: '▲', tone: 'neutral' });
  assert.deepEqual(diffTone('defense', 10, 10), { arrow: '', tone: 'same' });
});
