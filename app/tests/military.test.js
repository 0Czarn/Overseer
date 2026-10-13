import test from 'node:test';
import assert from 'node:assert/strict';
import { designerLines, manpowerText, shortCount, statText, unitLines } from '../renderer/views/military.js';

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

test('free manpower like the game tooltip (SOV 1941: 461 566 = 461.56K)', () => {
  assert.equal(manpowerText(461566), '461.56K');
  assert.equal(manpowerText(4640000), '4.64M');
  assert.equal(manpowerText(null), '—');
});

test('designer stats cut off like the game (SOV Strelkovaya Diviziya, dywizja.png)', () => {
  const groups = Object.fromEntries(designerLines({ soft_attack: 122.962, hard_attack: 40.467, max_strength: 301.7,
    supply_consumption: 0.768, initiative: 0.22, experience_loss_factor: -0.25, maximum_speed: 4, combat_width: 18, manpower: 11640 })
    .map(([title, rows]) => [title, Object.fromEntries(rows)]));
  assert.equal(groups['Combat Stats']['Soft Attack'], '122.9');
  assert.equal(groups['Combat Stats']['Hard Attack'], '40.4');
  assert.equal(groups['Combat Stats']['Initiative'], '22.00%');
  assert.equal(groups['Base Stats'].HP, '301.7');
  assert.equal(groups['Base Stats']['Supply Use'], '0.76');
  assert.equal(groups['Base Stats']['Max Speed'], '4.0 km/h');
  assert.equal(groups.Cost.Manpower, '11640');
  assert.equal(groups['Base Stats']['Exp. Loss'], '-25.00%');
  assert.equal(groups['Base Stats'].Organization, undefined);
});
