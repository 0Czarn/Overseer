import test from 'node:test';
import assert from 'node:assert/strict';
import { designDate, designerLines, gridColumns, manpowerText, shortCount, slotLabel, slotRows, splitDesigns, statText, unitLines } from '../renderer/views/military.js';

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

test('designer grid: slot = column * 5 + row, short arrays padded with empty slots', () => {
  const slots = ['infantry', 'infantry', 'infantry', null, null, 'infantry', null, null, null, null, 'artillery_brigade'];
  const cols = gridColumns(slots);
  assert.equal(cols.length, 5);
  assert.deepEqual(cols[0], ['infantry', 'infantry', 'infantry', null, null]);
  assert.deepEqual(cols[1], ['infantry', null, null, null, null]);
  assert.deepEqual(cols[2], ['artillery_brigade', null, null, null, null]);
  assert.deepEqual(cols[4], [null, null, null, null, null]);
});

test('plane designs: outdated ones apart, older versions counted, dates first seen', () => {
  const d = (id, name, type, outdated, parent, extra = {}) => ({ id, name, type_name: type, outdated, parent, stats: {}, ...extra });
  const designs = [
    d(1695, 'Inter-War Small Airframe', 'Inter-War Small Airframe', true, null),
    d(1711, 'PZL P.11', 'Inter-War Small Airframe', true, 1695),
    d(1713, 'PZL P.23', 'Basic Close Air Support', true, null),
    d(4505, 'PZL P.23', 'Basic Close Air Support', false, 1713),
    d(1697, 'Basic Small Airframe', 'Basic Small Airframe', false, null)];
  const { current, decommissioned } = splitDesigns(designs);
  assert.deepEqual(current.map((x) => [x.id, x.olderCount]), [[4505, 1], [1697, 0]]);   // named designs first
  assert.deepEqual(decommissioned.map((x) => [x.id, x.replacedBy.length]), [[1711, 0], [1713, 1], [1695, 0]]);
  assert.equal(designDate({ seen: '1936.05.18', seen_before: false }), '1936.05.18');
  assert.equal(designDate({ seen: '1936.05.01', seen_before: true }), 'before 1936.05.01');
  assert.equal(designDate({ seen: null }), 'unknown');
});

test('plane designer slots: weapons on top, engine and specials below', () => {
  const slots = [{ slot: 'fixed_main_weapon_slot', module: 'bomb_locks' }, { slot: 'fixed_auxiliary_weapon_slot_1', module: null },
    { slot: 'engine_type_slot', module: 'engine_2_1x' }, { slot: 'special_type_slot_1', module: 'lmg_defense_turret' }];
  const [top, bottom] = slotRows(slots);
  assert.deepEqual(top.map((s) => slotLabel(s.slot)), ['Main weapon', 'Weapon 2']);
  assert.deepEqual(bottom.map((s) => slotLabel(s.slot)), ['Engine', 'Special 1']);
});
