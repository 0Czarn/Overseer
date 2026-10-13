import test from 'node:test';
import assert from 'node:assert/strict';
import { shortCount, statText, unitLines } from '../renderer/views/military.js';

test('counts shortened like the game top bar (SOV: 4,345,676 men in the field = 4M)', () => {
  assert.equal(shortCount(4345676), '4.34M');
  assert.equal(shortCount(38250), '38.2K');
  assert.equal(shortCount(950), '950');
  assert.equal(shortCount(null), '—');
});

test('template parts and plane stats like the game tooltips (I-16)', () => {
  assert.deepEqual(unitLines([{ count: 9, name: 'Infantry' }, { count: 3, name: 'Anti-Air Battery' }]), ['9 Infantry', '3 Anti-Air Battery']);
  assert.equal(statText('reliability', 0.8), '80.0%');
  assert.equal(statText('maximum_speed', 425), '425 km/h');
  assert.equal(statText('range', 550), '550 km');
  assert.equal(statText('fuel_consumption', 0.21), '0.21');
});
